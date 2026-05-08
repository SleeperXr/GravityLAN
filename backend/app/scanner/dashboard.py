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
    
    # 1. Dashboard Health Check (Check ALL services for ALL known devices)
    async with async_session() as db:
        from sqlalchemy.orm import selectinload
        from app.scanner.port_scanner import scan_ports
        
        res_dev = await db.execute(
            select(Device).options(selectinload(Device.services))
        )
        devices = res_dev.scalars().all()
        
        logger.info(f"Dashboard: Starting deep health check for {len(devices)} devices.")
        
        # We scan in small batches to not overwhelm the network but still be fast
        batch_size = 5
        for i in range(0, len(devices), batch_size):
            batch = devices[i:i+batch_size]
            health_tasks = []
            
            for dev in batch:
                if progress_callback: await progress_callback(f"Checking {dev.display_name} services...")
                
                # We check ALL services defined for this device
                target_ports = [s.port for s in dev.services]
                if not target_ports:
                    target_ports = MANAGEMENT_PORTS[:5] # Default fallback
                
                health_tasks.append(scan_ports(dev.ip, ports=target_ports, timeout=0.8))
            
            # Run batch health check
            batch_results = await asyncio.gather(*health_tasks)
            
            for dev, open_ports in zip(batch, batch_results):
                is_online = len(open_ports) > 0
                dev.is_online = is_online
                if is_online:
                    dev.last_seen = datetime.now()
                
                # Update each service
                for svc in dev.services:
                    svc.is_up = svc.port in open_ports
                    svc.last_checked = datetime.now()
            
            await db.commit()

    # 2. Aggressive Subnet Discovery (Finding NEW interesting devices)
    from app.scanner.port_scanner import nmap_scan
    from app.scanner.classifier import classify_device
    all_found_count = 0
    
    for subnet in subnets:
        if progress_callback: await progress_callback(f"Aggressive scan on {subnet}...")
        
        import ipaddress
        if "/" not in subnet:
             if subnet.count(".") == 2: subnet = f"{subnet}.0/24"
             else: subnet = f"{subnet}/24"
        
        # We use a more "brute force" discovery for the dashboard: 
        # Scan the subnet for ANY management ports directly.
        # This is the "Strongest Scanner" logic.
        from app.scanner.discovery import discover_hosts_simple
        
        # Step A: Fast ping discovery to find ALIVE hosts
        net = ipaddress.ip_network(subnet, strict=False)
        target_ips = [str(ip) for ip in net.hosts()]
        alive_hosts = await discover_hosts_simple(target_ips)
        resolved_hosts = await resolve_mac_addresses(alive_hosts)
        
        for host in resolved_hosts:
            ip = host["ip"]
            mac = host.get("mac")
            
            # Step B: Deep-check hosts not already in Dashboard
            is_dashboard = any(d.ip == ip for d in devices)
            if not is_dashboard:
                if progress_callback: await progress_callback(f"Analyzing {ip}...")
                
                # Heavy duty port check
                found_ports = await scan_ports(ip, ports=MANAGEMENT_PORTS, timeout=0.5)
                
                # If it has management ports, it's a high-priority "Newly Discovered" device
                if found_ports:
                    logger.info(f"Dashboard: High-priority device found: {ip} (Ports: {found_ports})")
                    # We can even trigger a classification here to get the best name/icon
                    classification = classify_device({"ip": ip, "ports": found_ports})
                    hostname = host.get("hostname") or classification.get("hostname")
                    
                    await sync_host_to_db(
                        ip=ip,
                        mac=mac,
                        hostname=hostname,
                        vendor=host.get("vendor"),
                        ports=found_ports,
                        is_planner_scan=False # This puts it into discovered_hosts
                    )
                    all_found_count += 1
                else:
                    # Still sync it as a low-priority discovery
                    await sync_host_to_db(
                        ip=ip,
                        mac=mac,
                        hostname=host.get("hostname"),
                        is_planner_scan=False
                    )
            else:
                # Host is already in dashboard, sync_host_to_db will update its online status
                await sync_host_to_db(
                    ip=ip,
                    mac=mac,
                    hostname=host.get("hostname"),
                    is_planner_scan=False
                )

    return all_found_count
