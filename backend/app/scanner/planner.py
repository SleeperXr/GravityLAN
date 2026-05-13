"""Network Planner Scan logic — Fast discovery via ARP/Ping/DNS."""

import asyncio
import logging
import ipaddress
from datetime import datetime, timezone
from sqlalchemy import select, delete, or_
from app.database import async_session
from app.models.device import DiscoveredHost, Device
from app.models.network import Subnet
from app.scanner.discovery import discover_hosts_simple
from app.scanner.arp import resolve_mac_addresses, get_local_arp_table
from app.scanner.sync import sync_host_to_db
from app.services.cache_service import discovery_cache, dashboard_cache, topology_cache

logger = logging.getLogger(__name__)

async def run_arp_only_scan():
    """
    Extremely fast scan that only looks at the local ARP table.
    Used for the Turbo mode. Filters results by configured scan_subnets.
    """
    async with async_session() as db:
        from app.models.setting import Setting
        res = await db.execute(select(Setting).where(Setting.key == "scan_subnets"))
        setting = res.scalar_one_or_none()
        
        allowed_nets = []
        if setting and setting.value:
            for s in setting.value.split(","):
                try: allowed_nets.append(ipaddress.ip_network(s.strip(), strict=False))
                except ValueError:
                    pass
        else:
            # Fallback: Ignore virtual subnets from local interfaces
            from app.scanner.scheduler import _get_auto_scan_subnets
            for s in _get_auto_scan_subnets():
                try: allowed_nets.append(ipaddress.ip_network(s, strict=False))
                except ValueError:
                    pass

    arp_hosts = get_local_arp_table()
    synced_count = 0
    for ip, mac in arp_hosts.items():
        if not mac or mac == "00:00:00:00:00:00":
            continue
            
        # Check if IP is in one of the allowed subnets
        try:
            ip_obj = ipaddress.IPv4Address(ip)
            if any(ip_obj in net for net in allowed_nets):
                await sync_host_to_db(ip=ip, mac=mac, is_planner_scan=True)
                synced_count += 1
        except (ValueError, OSError):
            pass
        
    return synced_count

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
            
        # NEW: Find specific DNS server for this subnet
        dns_server = None
        async with async_session() as db:
            res_sub = await db.execute(select(Subnet).where(Subnet.cidr == subnet))
            sub_obj = res_sub.scalar_one_or_none()
            if sub_obj:
                dns_server = sub_obj.dns_server
                if dns_server:
                    logger.info(f"Planner: Using custom DNS {dns_server} for subnet {subnet}")

        if progress_callback:
            await progress_callback(f"Scanner: Scanning {subnet} (ARP + Ping)...")
            
        # 1. Fast Discovery (Nmap -sn -PR -PE)
        try:
            # Convert subnet to list of IPs for the discovery function
            net = ipaddress.ip_network(subnet, strict=False)
            target_ips = [str(ip) for ip in net.hosts()]
        except ValueError as e:
            logger.error(f"Planner: Skipping invalid subnet '{subnet}': {e}")
            continue
            
        async def _on_host(h):
            # Immediate sync per host for real-time UI updates
            await sync_host_to_db(
                ip=h["ip"],
                mac=h.get("mac"),
                hostname=h.get("hostname"),
                is_planner_scan=True,
                should_invalidate_cache=False
            )
            if progress_callback:
                await progress_callback("EVENT:RELOAD_DEVICES")

        alive_hosts = await discover_hosts_simple(target_ips, dns_server=dns_server, host_found_callback=_on_host)
        
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
                is_planner_scan=True,
                should_invalidate_cache=False
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
                    net_obj = ipaddress.IPv4Network(s, strict=False)
                    if ipaddress.IPv4Address(host.ip) in net_obj:
                        is_in_scanned_subnet = True
                        break
                except (ValueError, OSError):
                    continue
            
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
             # Robust check for each subnet
             in_any_scanned = False
             for s in subnets:
                 try:
                     net_obj = ipaddress.IPv4Network(s, strict=False)
                     if ipaddress.IPv4Address(dev.ip) in net_obj:
                         in_any_scanned = True
                         break
                 except (ValueError, OSError):
                     continue
                     
             if in_any_scanned and dev.ip not in all_alive_ips:
                    dev.is_online = False
                    dev.status_changed_at = datetime.now(timezone.utc)
        
        await db.commit()
        # Consolidated cache invalidation
        discovery_cache.invalidate()
        dashboard_cache.invalidate_all()
        topology_cache.invalidate()

    logger.info(f"Planner: Scan complete. Found {total_found} hosts.")
    return total_found
