"""Shared synchronization logic for both Planner and Dashboard scans."""

import logging
from datetime import datetime, timezone
from sqlalchemy import select, delete, or_
from app.database import async_session
from app.models.device import Device, DiscoveredHost, Service
import json
from datetime import datetime, timedelta, timezone
from app.scanner.vendor import get_vendor
from app.scanner.utils import ping_host_async, ensure_utc
from app.scanner.hostname import is_ip_like
from app.services.cache_service import discovery_cache, dashboard_cache, topology_cache

logger = logging.getLogger(__name__)
 
IP_FLAP_THRESHOLD = timedelta(minutes=2)

async def sync_host_to_db(ip: str, mac: str | None, hostname: str | None = None, vendor: str | None = None, ports: list[int] | None = None, is_planner_scan: bool = True, should_invalidate_cache: bool = True):
    """
    Wrapper for sync_hosts_batch for single host updates.
    """
    host_data = {
        "ip": ip,
        "mac": mac,
        "hostname": hostname,
        "vendor": vendor,
        "ports": ports
    }
    return await sync_hosts_batch([host_data], is_planner_scan, should_invalidate_cache)

async def sync_hosts_batch(hosts: list[dict], is_planner_scan: bool = True, should_invalidate_cache: bool = True):
    """
    Synchronizes multiple hosts in a single database transaction.
    Significantly reduces I/O pressure and prevents 'Database is locked' errors.
    """
    if not hosts:
        return []

    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm.exc import StaleDataError
    import asyncio

    results = []
    async with async_session() as db:
        for host in hosts:
            try:
                res = await _sync_host_internal(db, is_planner_scan=is_planner_scan, **host)
                results.append(res)
            except Exception as e:
                logger.error(f"Sync: Failed to process host: {e}")

        # Commit with robust SQLite retry logic
        for attempt in range(5):
            try:
                await db.commit()
                break
            except StaleDataError:
                await db.rollback()
                logger.debug("Sync: Stale data encountered during batch commit, rolling back.")
                break
            except OperationalError as e:
                await db.rollback()
                error_msg = str(e).lower()
                if ("locked" in error_msg or "busy" in error_msg) and attempt < 4:
                    wait_time = (attempt + 1) * 0.2
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(f"Sync: Batch DB lock failure: {e}")
                raise

    if should_invalidate_cache:
        discovery_cache.invalidate()
        # Only invalidate dashboard/topology if a device was actually updated/matched
        # For performance, we could be more selective, but this is safer for now.
        dashboard_cache.invalidate_all()
        topology_cache.invalidate()
    
    return results

async def _sync_host_internal(db, ip: str, mac: str | None, hostname: str | None = None, vendor: str | None = None, ports: list[int] | None = None, is_planner_scan: bool = True):
    """
    Internal logic for syncing a single host. Does NOT commit.
    """
    is_valid_mac = bool(
        mac and mac.strip() 
        and mac.lower() not in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff") 
        and not mac.lower().startswith(("01:00:5e", "33:33"))
    )

    def _mac_is_valid(m: str | None) -> bool:
        return bool(
            m and m.strip() 
            and m.lower() not in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff") 
            and not m.lower().startswith(("01:00:5e", "33:33"))
        )

    # 1. Dashboard Check (Is this host already monitored?)
    dev = None
    dev_match_type = None

    # Step 1: Match by MAC AND IP (Exact match)
    if is_valid_mac and ip:
        res_exact = await db.execute(select(Device).where(Device.mac == mac, Device.ip == ip))
        dev = res_exact.scalar_one_or_none()
        if dev:
            dev_match_type = "exact"

    # Step 2: Match by IP only (provided device's MAC doesn't explicitly conflict with incoming MAC)
    if not dev and ip:
        res_dev_ip = await db.execute(select(Device).where(Device.ip == ip))
        cand_dev = res_dev_ip.scalar_one_or_none()
        if cand_dev:
            # If both incoming scan and candidate device have valid distinct MACs, reject candidate match
            if is_valid_mac and _mac_is_valid(cand_dev.mac) and cand_dev.mac.lower() != mac.lower():
                dev = None
            else:
                dev = cand_dev
                dev_match_type = "ip"

    # Step 3: Match by MAC only (ONLY IF exactly 1 device has this MAC!)
    if not dev and is_valid_mac:
        res_mac = await db.execute(select(Device).where(Device.mac == mac))
        mac_matches = res_mac.scalars().all()
        if len(mac_matches) == 1:
            dev = mac_matches[0]
            dev_match_type = "mac"
        elif len(mac_matches) > 1:
            logger.debug(f"Sync: Multiple devices found for MAC {mac} (ipvlan). Skipping MAC-only fallback matching.")

    # Step 4: Match by Hostname
    if not dev and hostname and not is_ip_like(hostname):
        res_dev_host = await db.execute(select(Device).where(Device.hostname == hostname))
        dev = res_dev_host.scalar_one_or_none()
        if dev:
            dev_match_type = "hostname"

    # 2. Discovery Table Deduplication & Search
    disc = None
    disc_match_type = None

    # Step 1: Match by MAC AND IP
    if is_valid_mac and ip:
        res_exact_disc = await db.execute(select(DiscoveredHost).where(DiscoveredHost.mac == mac, DiscoveredHost.ip == ip))
        disc = res_exact_disc.scalar_one_or_none()
        if disc:
            disc_match_type = "exact"

    # Step 2: Match by IP
    if not disc and ip:
        res_ip = await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == ip))
        cand_disc = res_ip.scalar_one_or_none()
        if cand_disc:
            if is_valid_mac and _mac_is_valid(cand_disc.mac) and cand_disc.mac.lower() != mac.lower():
                disc = None
            else:
                disc = cand_disc
                disc_match_type = "ip"

    # Step 3: Match by MAC (ONLY IF exactly 1 record matches)
    if not disc and is_valid_mac:
        res_macs = await db.execute(
            select(DiscoveredHost)
            .where(DiscoveredHost.mac == mac)
            .order_by(DiscoveredHost.is_monitored.desc(), DiscoveredHost.custom_name.desc())
        )
        matches = res_macs.scalars().all()
        if len(matches) == 1:
            disc = matches[0]
            disc_match_type = "mac"
        elif len(matches) > 1:
            logger.debug(f"Sync: Multiple DiscoveredHost records found for MAC {mac} (ipvlan). Skipping MAC-only matching.")

    # Step 4: Match by Hostname
    if not disc and hostname and not is_ip_like(hostname):
        res_disc_host = await db.execute(select(DiscoveredHost).where(DiscoveredHost.hostname == hostname))
        disc = res_disc_host.scalar_one_or_none()
        if disc:
            disc_match_type = "hostname"

    # 3. Apply Updates to DiscoveredHost
    if disc:
        if disc.ip != ip:
            await db.execute(delete(DiscoveredHost).where(DiscoveredHost.ip == ip).where(DiscoveredHost.id != disc.id))
            disc.ip = ip
            if hasattr(disc, 'ip_changed_at'):
                disc.ip_changed_at = datetime.now(timezone.utc)
        
        disc.is_online = True
        disc.last_seen = datetime.now(timezone.utc)
        if getattr(disc, 'ip_placeholder', False):
            disc.ip_placeholder = False
        if hostname: disc.hostname = hostname
        
        if is_valid_mac:
            if not _mac_is_valid(disc.mac):
                disc.mac = mac
                
        if vendor: disc.vendor = vendor
        if ports: disc.ports = json.dumps(ports)
        
        if not disc.custom_name and mac and dev:
            disc.custom_name = dev.display_name
        
        disc.is_monitored = dev is not None
    else:
        # Create new discovery record
        inherited_name = dev.display_name if (mac and dev) else None

        disc = DiscoveredHost(
            ip=ip, mac=mac, hostname=hostname,
            custom_name=inherited_name,
            vendor=vendor or (get_vendor(mac) if mac else None),
            is_online=True,
            is_monitored=dev is not None,
            last_seen=datetime.now(timezone.utc),
            first_seen=datetime.now(timezone.utc),
            ports=json.dumps(ports) if ports else None
        )
        db.add(disc)

    # 4. Cross-Sync to Dashboard
    if dev:
        dev.is_online = True
        dev.last_seen = datetime.now(timezone.utc)
        if getattr(dev, 'ip_placeholder', False):
            dev.ip_placeholder = False

        if is_valid_mac:
            if not _mac_is_valid(dev.mac):
                dev.mac = mac

        if disc and disc.custom_name:
            dev.display_name = disc.custom_name
        
        if dev.ip != ip:
            should_update_ip = True
            is_verified_change = bool(is_valid_mac and dev.mac and dev.mac.lower() == mac.lower() and dev_match_type in ("exact", "mac"))

            if should_update_ip:
                # To prevent UNIQUE constraint error on devices.ip:
                # check if another device already has the new IP.
                res_conflict = await db.execute(select(Device).where(Device.ip == ip).where(Device.id != dev.id))
                conflict_dev = res_conflict.scalar_one_or_none()
                if conflict_dev:
                    conflict_dev.is_online = False
                    conflict_dev.ip_placeholder = True
                    safe_ip = None
                    if conflict_dev.old_ip and not conflict_dev.old_ip.startswith("offline-") and is_ip_like(conflict_dev.old_ip):
                        res_taken = await db.execute(select(Device).where(Device.ip == conflict_dev.old_ip).where(Device.id != conflict_dev.id))
                        if not res_taken.scalar_one_or_none():
                            safe_ip = conflict_dev.old_ip
                    
                    if not safe_ip:
                        counter = 0
                        while True:
                            candidate = f"0.0.0.{counter}"
                            res_taken = await db.execute(select(Device).where(Device.ip == candidate).where(Device.id != conflict_dev.id))
                            if not res_taken.scalar_one_or_none():
                                safe_ip = candidate
                                break
                            counter += 1
                    
                    conflict_dev.ip = safe_ip
                    await db.flush()
                    logger.warning(f"Sync: Resolved IP conflict. Moved conflicting device {conflict_dev.id} to placeholder IP {conflict_dev.ip}")

                dev.old_ip = dev.ip
                dev.ip = ip
                dev.ip_changed_at = datetime.now(timezone.utc)

                # ONLY emit DeviceHistory event if IP change is VERIFIED
                if is_verified_change:
                    from app.models.device import DeviceHistory
                    db.add(DeviceHistory(
                        device_id=dev.id,
                        status="info",
                        message=f"IP changed from {dev.old_ip} to {ip}"
                    ))
                else:
                    logger.info(f"Sync: Updated IP of device {dev.id} to {ip} without DeviceHistory notification (unverified match).")

    return disc

async def sync_docker_containers(containers: list[dict]):
    """
    Syncs local Docker container statuses to the database.
    If a container is 'running', it overrides the offline status in the DB.
    """
    async with async_session() as db:
        for container in containers:
            ips = container.get("ips", [])
            is_running = container.get("status") == "running"
            
            if not ips or not is_running:
                continue
                
            for ip in ips:
                # Update discovered hosts
                res_disc = await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == ip))
                disc = res_disc.scalar_one_or_none()
                if disc:
                    if not disc.is_online:
                        logger.info(f"Docker Sync: Marking container {container['name']} ({ip}) as ONLINE via Docker")
                    disc.is_online = True
                    disc.last_seen = datetime.now(timezone.utc)
                    # Optionally update name if unknown
                    if not disc.custom_name or disc.custom_name == "Unknown":
                        disc.custom_name = container["name"]

                # Update dashboard devices
                res_dev = await db.execute(select(Device).where(Device.ip == ip))
                dev = res_dev.scalar_one_or_none()
                if dev:
                    if not dev.is_online:
                        logger.info(f"Docker Sync: Marking dashboard container {dev.display_name} ({ip}) as ONLINE via Docker")
                    dev.is_online = True
                    dev.last_seen = datetime.now(timezone.utc)
        
        await db.commit()
        discovery_cache.invalidate()
        dashboard_cache.invalidate_all()
        topology_cache.invalidate()
