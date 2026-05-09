"""Shared synchronization logic for both Planner and Dashboard scans."""

import logging
from datetime import datetime
from sqlalchemy import select, delete, or_
from app.database import async_session
from app.models.device import Device, DiscoveredHost, Service
import json
from datetime import datetime, timedelta
from app.scanner.vendor import get_vendor
from app.scanner.discovery import _ping_host_async
from app.scanner.hostname import is_ip_like

logger = logging.getLogger(__name__)
 
IP_FLAP_THRESHOLD = timedelta(minutes=2)

async def sync_host_to_db(ip: str, mac: str | None, hostname: str | None = None, vendor: str | None = None, ports: list[int] | None = None, is_planner_scan: bool = True):
    """
    Core synchronization logic. 
    Handles MAC-based identity, deduplication, and cross-table status updates.
    """
    async with async_session() as db:
        # 1. Dashboard Check (Is this host already monitored?)
        dev = None
        if mac:
            res_dev = await db.execute(select(Device).where(Device.mac == mac))
            dev = res_dev.scalar_one_or_none()
        
        if not dev:
            res_dev_ip = await db.execute(select(Device).where(Device.ip == ip))
            dev = res_dev_ip.scalar_one_or_none()
        
        if not dev and hostname and not is_ip_like(hostname):
            # NEW: Fallback for MAC-less devices (IOT subnets)
            # Match by hostname to preserve dashboard labels
            res_dev_host = await db.execute(select(Device).where(Device.hostname == hostname))
            dev = res_dev_host.scalar_one_or_none()
            if dev:
                logger.info(f"Sync: Matched device {hostname} by Hostname (MAC missing)")

        # 2. Discovery Table Deduplication & Search
        disc = None
        if mac:
            # Find all records with this MAC, keep best, delete others
            res_macs = await db.execute(
                select(DiscoveredHost)
                .where(DiscoveredHost.mac == mac)
                .order_by(DiscoveredHost.is_monitored.desc(), DiscoveredHost.custom_name.desc())
            )
            matches = res_macs.scalars().all()
            if matches:
                disc = matches[0]
                if len(matches) > 1:
                    logger.info(f"Sync: Deduplicating {len(matches)} records for MAC {mac}")
                    for extra in matches[1:]:
                        await db.delete(extra)
        
        if not disc:
            # Fallback to IP search
            res_ip = await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == ip))
            disc = res_ip.scalar_one_or_none()

        # 3. Apply Updates
        if disc:
            # Handle IP change with Anti-Flap logic
            if disc.ip != ip:
                # If the host was seen VERY recently at the old IP, it's likely a multi-interface device (LAN/WLAN)
                # In this case, we don't want to flip-flop the primary IP in the DB every few seconds.
                is_stale = (datetime.now() - disc.last_seen) > IP_FLAP_THRESHOLD
                
                if not is_stale:
                    # Optional: Check if old IP is still alive. If yes, don't move.
                    # This is a bit expensive, so we only do it if the flap is recent.
                    logger.debug(f"Sync: Potential flap detected for {mac} ({disc.ip} vs {ip}). Checking stickiness...")
                    # For now, we just stick to the first one found in a scan window
                    # and ignore the second one to stop the log spam.
                    pass 
                else:
                    logger.info(f"Sync: Host moved {mac or 'Unknown'} from {disc.ip} -> {ip}")
                    # Clear the new IP from stale records to maintain uniqueness
                    await db.execute(delete(DiscoveredHost).where(DiscoveredHost.ip == ip).where(DiscoveredHost.id != disc.id))
                    disc.ip = ip
                    if hasattr(disc, 'ip_changed_at'):
                        disc.ip_changed_at = datetime.now()
            
            disc.is_online = True
            disc.last_seen = datetime.now()
            if hostname: disc.hostname = hostname
            if mac: disc.mac = mac
            if vendor: disc.vendor = vendor # Use passed vendor
            if ports: disc.ports = json.dumps(ports)
            
            # Inherit custom name if missing
            if not disc.custom_name and mac:
                if dev and dev.display_name:
                    disc.custom_name = dev.display_name
            
            disc.is_monitored = dev is not None
        else:
            # Create new discovery record
            inherited_name = None
            if mac and dev:
                inherited_name = dev.display_name

            disc = DiscoveredHost(
                ip=ip, mac=mac, hostname=hostname,
                custom_name=inherited_name,
                vendor=vendor or (get_vendor(mac) if mac else None),
                is_online=True,
                is_monitored=dev is not None,
                last_seen=datetime.now(),
                first_seen=datetime.now(),
                ports=json.dumps(ports) if ports else None
            )
            db.add(disc)

        # 4. Cross-Sync to Dashboard
        if dev:
            if not dev.is_online:
                logger.info(f"Sync: Dashboard device {dev.ip} ({dev.display_name}) back ONLINE via scan")
            
            dev.is_online = True
            dev.last_seen = datetime.now()
            if mac: dev.mac = mac
            if disc and disc.custom_name: dev.display_name = disc.custom_name
            # Sticky Dashboard IP: Only update if the move is stable (not flapping)
            if dev.ip != ip:
                is_stale = (datetime.now() - (dev.last_seen or datetime.min)) > IP_FLAP_THRESHOLD
                if is_stale:
                    logger.info(f"Sync: Updating Dashboard IP for {dev.display_name}: {dev.ip} -> {ip}")
                    dev.ip = ip
                    dev.ip_changed_at = datetime.now()
                else:
                    logger.debug(f"Sync: Suppressing dashboard IP flap for {dev.display_name} ({dev.ip} -> {ip})")

        await db.commit()
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
                    disc.last_seen = datetime.now()
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
                    dev.last_seen = datetime.now()
        
        await db.commit()
