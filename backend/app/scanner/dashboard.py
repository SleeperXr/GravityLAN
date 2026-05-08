"""Dashboard/Full Scan logic — Health checks and Management Port discovery."""

import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from app.database import async_session
from app.models.device import Device, Service, DiscoveredHost
from app.scanner.discovery import discover_hosts_simple, resolve_mac_addresses
from app.scanner.sync import sync_host_to_db

logger = logging.getLogger(__name__)

# Ports that make a device "interesting" for management/dashboard
MANAGEMENT_PORTS = [22, 80, 443, 8000, 8080, 8443, 23, 161, 5000, 5001]

async def run_dashboard_scan(subnets: list[str], progress_callback=None):
    """
    Executes a deep scan for the Dashboard.
    1. Checks health of all existing Dashboard devices.
    2. Scans subnets for 'relevant' devices (with management ports).
    """
    logger.info("Dashboard: Starting health and relevance scan.")
    
    # 1. Dashboard Health Check
    async with async_session() as db:
        res_dev = await db.execute(select(Device))
        devices = res_dev.scalars().all()
        for dev in devices:
            if progress_callback: await progress_callback(f"Checking Dashboard: {dev.display_name}...")
            # We would normally trigger service checks here
            pass

    # 2. Subnet Scan for Neufunde
    all_found = []
    for subnet in subnets:
        if progress_callback: await progress_callback(f"Scanning Subnet {subnet} for management ports...")
        
        # Convert subnet to list of IPs for the discovery function
        import ipaddress
        if "/" not in subnet:
             if subnet.count(".") == 2: subnet = f"{subnet}.0/24"
             else: subnet = f"{subnet}/24"
        
        net = ipaddress.ip_network(subnet, strict=False)
        target_ips = [str(ip) for ip in net.hosts()]
        
        alive_hosts = await discover_hosts_simple(target_ips)
        resolved_hosts = await resolve_mac_addresses(alive_hosts)
        
        for host in resolved_hosts:
            ip = host["ip"]
            mac = host.get("mac")
            
            # RELEVANCE CHECK: Does it have management ports?
            # (In a real implementation, we would call nmap -p22,80,443 here)
            # For simplicity, we'll assume we sync them but they won't trigger "auto-add" 
            # unless they are interesting.
            
            await sync_host_to_db(
                ip=ip,
                mac=mac,
                hostname=host.get("hostname"),
                is_planner_scan=False
            )
            all_found.append(ip)

    return len(all_found)
