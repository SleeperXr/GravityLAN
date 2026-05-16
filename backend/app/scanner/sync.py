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
                logger.error(f"Sync: Failed to process host {host.get('ip')}: {e}")

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
    # 1. Dashboard Check (Is this host already monitored?)
    dev = None
    if mac:
        res_dev = await db.execute(select(Device).where(Device.mac == mac))
        dev = res_dev.scalar_one_or_none()
    
    if not dev:
        res_dev_ip = await db.execute(select(Device).where(Device.ip == ip))
        dev = res_dev_ip.scalar_one_or_none()
    
    if not dev and hostname and not is_ip_like(hostname):
        res_dev_host = await db.execute(select(Device).where(Device.hostname == hostname))
        dev = res_dev_host.scalar_one_or_none()

    # 2. Discovery Table Deduplication & Search
    disc = None
    if mac:
        res_macs = await db.execute(
            select(DiscoveredHost)
            .where(DiscoveredHost.mac == mac)
            .order_by(DiscoveredHost.is_monitored.desc(), DiscoveredHost.custom_name.desc())
        )
        matches = res_macs.scalars().all()
        if matches:
            disc = matches[0]
            if len(matches) > 1:
                for extra in matches[1:]:
                    await db.delete(extra)
    
    if not disc:
        res_ip = await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == ip))
        disc = res_ip.scalar_one_or_none()

    # 3. Apply Updates
    if disc:
        if disc.ip != ip:
            last_seen = ensure_utc(disc.last_seen)
            is_stale = not last_seen or (datetime.now(timezone.utc) - last_seen) > IP_FLAP_THRESHOLD
            
            if is_stale:
                # Clear the new IP from stale records
                await db.execute(delete(DiscoveredHost).where(DiscoveredHost.ip == ip).where(DiscoveredHost.id != disc.id))
                disc.ip = ip
                if hasattr(disc, 'ip_changed_at'):
                    disc.ip_changed_at = datetime.now(timezone.utc)
        
        disc.is_online = True
        disc.last_seen = datetime.now(timezone.utc)
        if hostname: disc.hostname = hostname
        if mac: disc.mac = mac
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
        if mac: dev.mac = mac
        if disc and disc.custom_name: dev.display_name = disc.custom_name
        
        if dev.ip != ip:
            last_seen = ensure_utc(dev.last_seen)
            is_stale = not last_seen or (datetime.now(timezone.utc) - last_seen) > IP_FLAP_THRESHOLD
            if is_stale:
                dev.ip = ip
                dev.ip_changed_at = datetime.now(timezone.utc)
    
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
