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
        from sqlalchemy.orm import selectinload
        from app.scanner.port_scanner import scan_ports
        
        res_dev = await db.execute(
            select(Device).options(selectinload(Device.services))
        )
        devices = res_dev.scalars().all()
        
        for dev in devices:
            if progress_callback: await progress_callback(f"Checking Dashboard: {dev.display_name}...")
            
            # Check if any port is open to determine online status
            target_ports = [s.port for s in dev.services if s.is_up or s.is_auto_detected]
            if not target_ports:
                # Fallback to standard management ports if no services defined
                target_ports = MANAGEMENT_PORTS[:3] # 22, 80, 443
            
            open_ports = await scan_ports(dev.ip, ports=target_ports, timeout=0.5)
            is_online = len(open_ports) > 0
            
            # Update device status
            dev.is_online = is_online
            dev.last_seen = datetime.now() if is_online else dev.last_seen
            
            # Update individual service status
            for svc in dev.services:
                if svc.port in open_ports:
                    svc.is_up = True
                    svc.last_checked = datetime.now()
                elif svc.port in target_ports:
                    svc.is_up = False
                    svc.last_checked = datetime.now()
            
        await db.commit()

    # 2. Subnet Scan for Neufunde (Port-aware)
    from app.scanner.port_scanner import nmap_scan
    all_found = []
    for subnet in subnets:
        if progress_callback: await progress_callback(f"Scanning Subnet {subnet} for management ports...")
        
        import ipaddress
        if "/" not in subnet:
             if subnet.count(".") == 2: subnet = f"{subnet}.0/24"
             else: subnet = f"{subnet}/24"
        
        net = ipaddress.ip_network(subnet, strict=False)
        target_ips = [str(ip) for ip in net.hosts()]
        
        # Use nmap with management ports for discovery
        alive_hosts = await discover_hosts_simple(target_ips) # Fast ping first
        resolved_hosts = await resolve_mac_addresses(alive_hosts)
        
        for host in resolved_hosts:
            ip = host["ip"]
            mac = host.get("mac")
            
            # For each alive host, check if it has interesting ports
            # (We only do this for hosts not already in the dashboard to save time)
            is_dashboard = any(d.ip == ip for d in devices)
            if not is_dashboard:
                # Quick port check for relevance
                found_ports = await scan_ports(ip, ports=MANAGEMENT_PORTS, timeout=0.3)
                if found_ports:
                    logger.info(f"Dashboard: Found interesting host {ip} with ports {found_ports}")
            
            await sync_host_to_db(
                ip=ip,
                mac=mac,
                hostname=host.get("hostname"),
                is_planner_scan=False
            )
            all_found.append(ip)

    return len(all_found)
