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
    
    # 1. Fast Discovery Phase (Ping + ARP) - The Planner logic
    # This finds out who is generally "alive" in the network very quickly.
    from app.scanner.discovery import discover_hosts_simple
    all_resolved_hosts = []
    
    for subnet in subnets:
        if progress_callback: await progress_callback(f"Ping/ARP discovery on {subnet}...")
        
        import ipaddress
        if "/" not in subnet:
             if subnet.count(".") == 2: subnet = f"{subnet}.0/24"
             else: subnet = f"{subnet}/24"
        
        net = ipaddress.ip_network(subnet, strict=False)
        target_ips = [str(ip) for ip in net.hosts()]
        
        # Fast ping discovery
        alive_hosts = await discover_hosts_simple(target_ips)
        resolved = await resolve_mac_addresses(alive_hosts)
        all_resolved_hosts.extend(resolved)
        
    # Map for quick lookup
    alive_map = {h["ip"]: h for h in all_resolved_hosts}

    # 2. Deep Health & Service Phase
    async with async_session() as db:
        from sqlalchemy.orm import selectinload
        from app.scanner.port_scanner import scan_ports
        
        res_dev = await db.execute(
            select(Device).options(selectinload(Device.services))
        )
        devices = res_dev.scalars().all()
        
        logger.info(f"Dashboard: Verifying services for {len(devices)} devices.")
        
        batch_size = 8
        for i in range(0, len(devices), batch_size):
            batch = devices[i:i+batch_size]
            health_tasks = []
            
            for dev in batch:
                is_ping_alive = dev.ip in alive_map
                
                # We check services if it's ping-alive OR if we want to be sure (ICMP might be blocked)
                target_ports = [s.port for s in dev.services]
                if not target_ports:
                    target_ports = MANAGEMENT_PORTS[:3]
                
                # If it's not even ping-alive, we do a very quick single-port check as fallback
                # If it is ping-alive, we do the full service check
                timeout = 0.4 if is_ping_alive else 0.2
                health_tasks.append(scan_ports(dev.ip, ports=target_ports, timeout=timeout))
            
            batch_results = await asyncio.gather(*health_tasks)
            
            for dev, open_ports in zip(batch, batch_results):
                # Device is online if it responded to Ping/ARP OR has open ports
                is_ping_alive = dev.ip in alive_map
                is_port_alive = len(open_ports) > 0
                is_online = is_ping_alive or is_port_alive
                
                dev.is_online = is_online
                if is_online:
                    dev.last_seen = datetime.now()
                    # Update MAC/Vendor if we found it via ARP now but didn't have it
                    if is_ping_alive and not dev.mac:
                        dev.mac = alive_map[dev.ip].get("mac")
                        if dev.mac: dev.vendor = alive_map[dev.ip].get("vendor")
                
                # Update individual services
                for svc in dev.services:
                    svc.is_up = svc.port in open_ports
                    svc.last_checked = datetime.now()
            
            await db.commit()

    # 3. Intelligent Discovery Phase (Sync Neufunde)
    from app.scanner.classifier import classify_device
    new_found_count = 0
    
    for host in all_resolved_hosts:
        ip = host["ip"]
        mac = host.get("mac")
        
        # Check if already in dashboard
        is_dashboard = any(d.ip == ip for d in devices)
        
        if not is_dashboard:
            # Check if it's "interesting" (Strongest Scanner logic)
            # We already know it's alive from Phase 1
            found_ports = await scan_ports(ip, ports=MANAGEMENT_PORTS, timeout=0.4)
            
            if found_ports:
                classification = classify_device({"ip": ip, "ports": found_ports})
                hostname = host.get("hostname") or classification.get("hostname")
                
                await sync_host_to_db(
                    ip=ip,
                    mac=mac,
                    hostname=hostname,
                    vendor=host.get("vendor"),
                    ports=found_ports,
                    is_planner_scan=False
                )
                new_found_count += 1
            else:
                # Still sync as a regular discovered host (Planner style)
                await sync_host_to_db(
                    ip=ip,
                    mac=mac,
                    hostname=host.get("hostname"),
                    is_planner_scan=False
                )
        else:
            # Just ensure the discovered_host entry is also kept fresh
            await sync_host_to_db(
                ip=ip,
                mac=mac,
                hostname=host.get("hostname"),
                is_planner_scan=False
            )

    return new_found_count
