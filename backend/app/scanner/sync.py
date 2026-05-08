"""Shared synchronization logic for both Planner and Dashboard scans."""

import logging
from datetime import datetime
from sqlalchemy import select, delete, or_
from app.database import async_session
from app.models.device import Device, DiscoveredHost, Service
import json
from app.scanner.vendor import get_vendor

logger = logging.getLogger(__name__)

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
            # Handle IP change
            if disc.ip != ip:
                logger.info(f"Sync: Host moved {mac or 'Unknown'} from {disc.ip} -> {ip}")
                # Clear the new IP from stale records
                await db.execute(delete(DiscoveredHost).where(DiscoveredHost.ip == ip).where(DiscoveredHost.id != disc.id))
                disc.ip = ip
            
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
            # If IP changed in discovery but dev is still at old IP, update it
            if dev.ip != ip:
                logger.info(f"Sync: Updating Dashboard IP for {dev.display_name}: {dev.ip} -> {ip}")
                dev.ip = ip

        await db.commit()
        return disc
