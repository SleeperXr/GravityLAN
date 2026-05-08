"""Network Planner Scan logic — Fast discovery via ARP/Ping/DNS."""

import asyncio
import logging
import ipaddress
from datetime import datetime
from sqlalchemy import select, delete, or_
from app.database import async_session
from app.models.device import DiscoveredHost, Device
from app.scanner.discovery import discover_hosts_simple, resolve_mac_addresses, get_local_arp_table
from app.scanner.sync import sync_host_to_db

logger = logging.getLogger(__name__)

async def run_arp_only_scan():
    """
    Extremely fast scan that only looks at the local ARP table.
    Used for the Turbo mode.
    """
    arp_hosts = get_local_arp_table()
    for ip, mac in arp_hosts.items():
        if mac and mac != "00:00:00:00:00:00":
            await sync_host_to_db(ip=ip, mac=mac, is_planner_scan=True)
    return len(arp_hosts)

async def run_planner_scan(subnets: list[str], progress_callback=None):
    """
    Executes a lightweight discovery scan for the Network Planner.
    Uses ARP + Ping + DNS.
    """
    # Ensure unique and normalized subnets
    normalized = []
    for s in set(subnets):
        if not s: continue
        if "/" not in s:
            if s.count(".") == 2: s = f"{s}.0/24"
            elif s.count(".") == 3: s = f"{s}/32"
            else: s = f"{s}/24"
        normalized.append(s)
    subnets = sorted(normalized)
    logger.info(f"Planner: Starting discovery on {subnets}")
    
    total_found = 0
    all_alive_ips = set()

    for subnet in subnets:
        if subnet.startswith("169.254."):
            continue
            
        if progress_callback:
            await progress_callback(f"Scanner: Scanning {subnet} (ARP + Ping)...")
            
        # 1. Fast Discovery (Nmap -sn -PR -PE)
        # Convert subnet to list of IPs for the discovery function
        if "/" not in subnet:
             if subnet.count(".") == 2: subnet = f"{subnet}.0/24"
             else: subnet = f"{subnet}/24"
        
        net = ipaddress.ip_network(subnet, strict=False)
        target_ips = [str(ip) for ip in net.hosts()]
        
        async def _on_host(h):
            # Immediate sync per host for real-time UI updates
            await sync_host_to_db(
                ip=h["ip"],
                mac=h.get("mac"),
                hostname=h.get("hostname"),
                is_planner_scan=True
            )
            if progress_callback:
                await progress_callback("EVENT:RELOAD_DEVICES")

        alive_hosts = await discover_hosts_simple(target_ips, host_found_callback=_on_host)
        
        if progress_callback:
            await progress_callback(f"Scanner: Found {len(alive_hosts)} active hosts. Resolving MACs...")

        # 2. MAC Resolution
        # This fills the ARP cache and returns host details
        resolved_hosts = await resolve_mac_addresses(alive_hosts)
        
        # 3. Sync to DB
        for host in resolved_hosts:
            ip = host["ip"]
            all_alive_ips.add(ip)
            await sync_host_to_db(
                ip=ip,
                mac=host.get("mac"),
                hostname=host.get("hostname"),
                is_planner_scan=True
            )
        
        total_found += len(resolved_hosts)

    # 4. Offline Cleanup (Exclusive to Planner)
    # Delete hosts in scanned subnets that were not found
    async with async_session() as db:
        res_disc = await db.execute(select(DiscoveredHost).where(DiscoveredHost.is_online == True))
        for host in res_disc.scalars().all():
            is_in_scanned_subnet = False
            for s in subnets:
                try:
                    if ipaddress.IPv4Address(host.ip) in ipaddress.IPv4Network(s, strict=False):
                        is_in_scanned_subnet = True
                        break
                except: continue
            
            if is_in_scanned_subnet and host.ip not in all_alive_ips:
                # IMPORTANT: Only delete if NOT monitored. 
                # Dashboard devices are handled by dashboard scanner.
                if not host.is_monitored:
                    logger.info(f"Planner: Host {host.ip} GONE, deleting.")
                    await db.delete(host)
                else:
                    # Just mark as offline for UI consistency until Dashboard scan confirms
                    host.is_online = False
        
        # Dashboard Sync: Set monitored devices to offline if they are in these subnets but not found
        res_dev = await db.execute(select(Device).where(Device.is_online == True))
        for dev in res_dev.scalars().all():
             if any(ipaddress.IPv4Address(dev.ip) in ipaddress.IPv4Network(s, strict=False) for s in subnets):
                if dev.ip not in all_alive_ips:
                    dev.is_online = False
                    dev.status_changed_at = datetime.now()
        
        await db.commit()

    logger.info(f"Planner: Scan complete. Found {total_found} hosts.")
    return total_found
