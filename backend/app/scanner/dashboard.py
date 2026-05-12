"""Dashboard/Full Scan logic — Health checks and Management Port discovery."""

import asyncio
import logging
import ipaddress
import os
from datetime import datetime
from sqlalchemy import select
from app.database import async_session
from app.models.device import Device, Service, DiscoveredHost
from app.models.network import Subnet
from app.scanner.discovery import discover_hosts_simple
from app.scanner.arp import resolve_mac_addresses
from app.scanner.sync import sync_host_to_db
from app.services.cache_service import discovery_cache, dashboard_cache, topology_cache

logger = logging.getLogger(__name__)

# Ports that make a device "interesting" for management/dashboard
MANAGEMENT_PORTS = [22, 80, 443, 8000, 8080, 8443, 23, 161, 5000, 5001]

async def run_dashboard_scan(subnets: list[str], progress_callback=None):
    """
    Executes a deep scan for the Dashboard.
    1. Checks health of all existing Dashboard devices.
    2. Scans subnets for 'relevant' devices (with management ports).
    """
    logger.info("Dashboard: Starting hybrid strongest scan (Ping/ARP + Port Health).")
    if progress_callback: await progress_callback("Dashboard: Starting discovery...")

    all_resolved_hosts = []
    # 1. Faster discovery phase (Planner style)
    for subnet in subnets:
        try:
            logger.info(f"Dashboard: Running discovery on {subnet}")
            
            # NEW: Find specific DNS server for this subnet
            dns_server = None
            async with async_session() as db:
                res_sub = await db.execute(select(Subnet).where(Subnet.cidr == subnet))
                sub_obj = res_sub.scalar_one_or_none()
                if sub_obj:
                    dns_server = sub_obj.dns_server
                    if dns_server:
                        logger.info(f"Dashboard: Using custom DNS {dns_server} for subnet {subnet}")

            if progress_callback: await progress_callback(f"Ping/ARP discovery on {subnet}...")
            
            net = ipaddress.ip_network(subnet, strict=False)
            target_ips = [str(ip) for ip in net.hosts()]
            
            async def _on_host(h):
                # We sync basic info immediately. Health/Ports will be handled in Phase 2/3.
                await sync_host_to_db(
                    ip=h["ip"],
                    mac=h.get("mac"),
                    hostname=h.get("hostname"),
                    is_planner_scan=False,
                    should_invalidate_cache=False
                )
                if progress_callback:
                    await progress_callback("EVENT:RELOAD_DEVICES")

            alive_hosts = await discover_hosts_simple(target_ips, dns_server=dns_server, host_found_callback=_on_host)
            resolved = await resolve_mac_addresses(alive_hosts)
            all_resolved_hosts.extend(resolved)
        except Exception as e:
            logger.error(f"Discovery failed for subnet {subnet}: {e}")
    
    logger.info(f"Dashboard: Discovery phase complete. Found {len(all_resolved_hosts)} potential hosts.")
    if not all_resolved_hosts:
        logger.warning("Dashboard: No hosts found in discovery phase.")
        # We still continue to health-check existing devices
    
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
        
        logger.info(f"Dashboard: Verifying health for {len(devices)} devices.")
        if progress_callback: await progress_callback(f"Verifying {len(devices)} devices...")
        
        batch_size = 8
        for i in range(0, len(devices), batch_size):
            batch = devices[i:i+batch_size]
            health_tasks = []
            
            for dev in batch:
                is_ping_alive = dev.ip in alive_map
                target_ports = [s.port for s in dev.services]
                if not target_ports:
                    target_ports = MANAGEMENT_PORTS[:3]
                
                timeout = 0.5 if is_ping_alive else 0.3
                health_tasks.append(scan_ports(dev.ip, ports=target_ports, timeout=timeout))
            
            batch_results = await asyncio.gather(*health_tasks)
            
            for dev, open_ports in zip(batch, batch_results):
                is_ping_alive = dev.ip in alive_map
                is_port_alive = len(open_ports) > 0
                
                # Special case: If this is the Docker Host and we have the socket, it is online
                from app.services.docker_service import docker_service
                host_ip = os.getenv("DOCKER_HOST_IP")
                is_docker_host = dev.ip == host_ip and docker_service.is_available()
                
                if is_docker_host:
                    logger.debug(f"Dashboard: Forcing {dev.ip} ONLINE (Docker Host match with socket)")
                
                is_online = is_ping_alive or is_port_alive or is_docker_host
                
                dev.is_online = is_online
                if is_online:
                    dev.last_seen = datetime.now()
                    if is_ping_alive and not dev.mac:
                        dev.mac = alive_map[dev.ip].get("mac")
                        if dev.mac: dev.vendor = alive_map[dev.ip].get("vendor")
                
                for svc in dev.services:
                    svc.is_up = svc.port in open_ports
                    svc.last_checked = datetime.now()
            
            await db.commit()
            # Invalidate once per batch or once at the end? 
            # Once at the end of the phase is better.
        
        dashboard_cache.invalidate_all()
        topology_cache.invalidate()

    # 3. Intelligent Discovery Phase (New Finds)
    from app.scanner.classifier import classify_device
    new_found_count = 0
    
    logger.info("Dashboard: Scanning for new management devices.")
    if progress_callback: await progress_callback("Searching for new devices...")
    
    for host in all_resolved_hosts:
        ip = host["ip"]
        mac = host.get("mac")
        
        # Check if already in dashboard (re-fetch to be safe)
        is_dashboard = any(d.ip == ip for d in devices)
        
        if not is_dashboard:
            # Check for management ports
            found_ports = await scan_ports(ip, ports=MANAGEMENT_PORTS, timeout=0.5)
            
            if found_ports:
                logger.info(f"Dashboard: Found potentially interesting new device at {ip} (Ports: {found_ports})")
                classification = classify_device({"ip": ip, "ports": found_ports})
                hostname = host.get("hostname") or classification.get("hostname")
                
                await sync_host_to_db(
                    ip=ip,
                    mac=mac,
                    hostname=hostname,
                    vendor=host.get("vendor"),
                    ports=found_ports,
                    is_planner_scan=False,
                    should_invalidate_cache=False
                )
                new_found_count += 1
            else:
                # Regular sync
                await sync_host_to_db(
                    ip=ip,
                    mac=mac,
                    hostname=host.get("hostname"),
                    is_planner_scan=False,
                    should_invalidate_cache=False
                )
        else:
            # Refresh discovered_host entry
            await sync_host_to_db(
                ip=ip,
                mac=mac,
                hostname=host.get("hostname"),
                is_planner_scan=False,
                should_invalidate_cache=False
            )

    logger.info(f"Dashboard scan finished. Discovered {new_found_count} new interesting devices.")
    # Final invalidation
    discovery_cache.invalidate()
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()
    return new_found_count
