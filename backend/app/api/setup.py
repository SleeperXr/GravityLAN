"""Setup wizard API — checks setup state and provides initial configuration."""

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.device import Device
from app.models.setting import Setting

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/status")
async def get_setup_status(db: AsyncSession = Depends(get_db)) -> dict:
    """Check if the initial setup has been completed.

    Returns:
        Dict with 'is_setup_complete' boolean and device count.
    """
    # Check if setup_complete flag is set in settings
    result = await db.execute(
        select(Setting).where(Setting.key == "setup.complete")
    )
    setting = result.scalar_one_or_none()

    device_count_result = await db.execute(select(func.count(Device.id)))
    device_count = device_count_result.scalar() or 0

    return {
        "is_setup_complete": setting is not None and setting.value == "true",
        "device_count": device_count,
    }


from pydantic import BaseModel

class SetupCompleteRequest(BaseModel):
    dns_server: str | None = None

@router.post("/complete")
async def mark_setup_complete(request: SetupCompleteRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Mark the initial setup as completed and migrate discovered hosts."""
    from app.models.device import DiscoveredHost, Device, Service
    from app.scanner.utils import ensure_default_groups, GROUP_TYPE_MAP
    from app.scanner.classifier import classify_device
    from app.scanner.hostname import resolve_hostname, is_ip_like
    from app.scanner.port_scanner import scan_ports
    from app.models.setting import Setting
    
    # 0. Save DNS server if provided
    if request.dns_server:
        dns_res = await db.execute(select(Setting).where(Setting.key == "dns.server"))
        dns_s = dns_res.scalar_one_or_none()
        if dns_s:
            dns_s.value = request.dns_server
        else:
            db.add(Setting(key="dns.server", value=request.dns_server, category="scan", description="Custom DNS server for hostname resolution"))
        await db.flush()

    # Get DNS server for better resolution
    dns_server = request.dns_server
    
    # 1. Prepare setup complete flag (will be committed at the end)
    res_setup = await db.execute(select(Setting).where(Setting.key == "setup.complete"))
    setting_complete = res_setup.scalar_one_or_none()
    if setting_complete:
        setting_complete.value = "true"
    else:
        db.add(Setting(key="setup.complete", value="true", category="system"))

    # 2. Automatically add all discovered online hosts to the dashboard
    host_result = await db.execute(select(DiscoveredHost).where(DiscoveredHost.is_online == True))
    discovered_hosts = host_result.scalars().all()
    
    if discovered_hosts:
        import asyncio
        group_map = await ensure_default_groups(db, commit=False)
        
        # Avoid IP duplicates
        existing_res = await db.execute(select(Device.ip))
        existing_ips = set(existing_res.scalars().all())
        
        async def process_host(host):
            if host.ip in existing_ips:
                return None
                
            # Quick discovery of key ports for better classification
            # We check for: SSH, HTTP, HTTPS, RDP, SMB, Proxmox, Synology
            found_ports = await scan_ports(host.ip, ports=[22, 80, 443, 3389, 445, 8006, 5001], timeout=0.4)
            
            # Try hostname resolution again if missing or just an IP
            current_hostname = host.hostname
            if is_ip_like(current_hostname):
                new_hname = await resolve_hostname(host.ip, timeout=1.5, dns_server=dns_server)
                if new_hname:
                    current_hostname = new_hname
                    host.hostname = new_hname

            classified = classify_device({
                "ip": host.ip, 
                "hostname": current_hostname, 
                "mac": host.mac, 
                "ports": found_ports
            }) or {"device_type": "unknown", "device_subtype": "Unknown", "services": []}
            
            device_type = classified.get("device_type", "unknown")
            group_name = GROUP_TYPE_MAP.get(device_type, "Neu entdeckt")
            group_id = group_map.get(group_name, group_map.get("Neu entdeckt"))
            
            # Format display name (strip domain)
            display_name = host.ip
            if current_hostname and not is_ip_like(current_hostname):
                display_name = current_hostname.split('.')[0]
            elif host.custom_name:
                display_name = host.custom_name
            
            device = Device(
                ip=host.ip, mac=host.mac, hostname=current_hostname, display_name=display_name,
                device_type=device_type, device_subtype=classified.get("device_subtype", "Unknown"),
                vendor=host.vendor, group_id=group_id, is_online=True
            )
            
            services = []
            if "services" in classified:
                for svc_data in classified["services"]:
                    services.append(Service(
                        name=svc_data["name"], protocol=svc_data["protocol"], port=svc_data["port"],
                        url_template=svc_data["url_template"], color=svc_data.get("color"),
                        is_auto_detected=True, is_up=True
                    ))
            
            # CRITICAL: Only add device if it has at least one service
            if not services:
                logger.info(f"Setup: Skipping auto-adoption for {host.ip} (No services found)")
                return None
            
            return (device, services, host)

        # Process all hosts in parallel
        tasks = [process_host(h) for h in discovered_hosts]
        results = await asyncio.gather(*tasks)
        
        for res in results:
            if not res: continue
            device, services, host = res
            db.add(device)
            await db.flush()
            for svc in services:
                svc.device_id = device.id
                db.add(svc)
            host.is_monitored = True

    await db.commit()
    return {"status": "ok"}
