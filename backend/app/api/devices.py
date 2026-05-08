import asyncio
import logging

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.device import Device, DeviceGroup, Service
from app.models.agent import AgentToken
from app.scanner.vendor import get_vendor
from app.scanner.hostname import resolve_hostname, is_ip_like
from app.schemas.device import (
    DeviceResponse,
    DeviceUpdate,
    DeviceHistoryResponse,
    ServiceResponse,
    ServiceCreate,
    ServiceUpdate,
    GroupCreate,
    GroupResponse,
    GroupUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    include_hidden: bool = False,
    group_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[DeviceResponse]:
    """List all discovered devices, optionally filtered by group."""
    query = select(Device)

    if not include_hidden:
        query = query.where(Device.is_hidden == False)  # noqa: E712

    if group_id is not None:
        query = query.where(Device.group_id == group_id)

    query = query.order_by(Device.sort_order, Device.display_name)
    result = await db.execute(query)
    devices = result.scalars().all()
    
    # Pre-populate has_agent and agent_info flags based on AgentToken existence
    from app.api.agent import LATEST_AGENT_VERSION
    for device in devices:
        token_q = await db.execute(select(AgentToken).where(AgentToken.device_id == device.id))
        token = token_q.scalar_one_or_none()
        device.has_agent = token is not None
        if token:
            device.agent_info = {
                "agent_version": token.agent_version,
                "latest_version": LATEST_AGENT_VERSION
            }

    return devices


@router.post("/refresh-all", status_code=200)
async def refresh_all_devices(db: AsyncSession = Depends(get_db)) -> dict:
    """Trigger a status and service check for all known devices."""
    try:
        from app.scanner.dashboard import run_dashboard_scan
        from app.scanner.utils import _get_local_subnets
        from app.api.devices import refresh_device_info
        from app.models.setting import Setting
        
        # 1. Fetch subnets for the scan
        res_sub = await db.execute(select(Setting).where(Setting.key == "scan_subnets"))
        s_set = res_sub.scalar_one_or_none()
        subnets = [s.strip() for s in s_set.value.split(",") if s.strip()] if s_set and s_set.value else [s.subnet for s in _get_local_subnets()]

        # 2. Basic online/offline check via Dashboard Scanner
        await run_dashboard_scan(subnets)
        
        # 2. Deep metadata refresh for all devices (Parallel processing)
        res = await db.execute(select(Device.id))
        device_ids = res.scalars().all()
        
        from app.database import async_session
        
        async def safe_refresh(d_id):
            async with async_session() as local_db:
                try:
                    await refresh_device_info(d_id, local_db, commit=True)
                except Exception as e:
                    logger.warning(f"Metadata refresh failed for device ID {d_id}: {e}")

        tasks = [safe_refresh(d_id) for d_id in device_ids]
        await asyncio.gather(*tasks)
        
        return {"status": "success", "message": f"All {len(device_ids)} devices refreshed"}
    except Exception as e:
        logger.error(f"Refresh all failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add-from-ip", response_model=DeviceResponse)
async def add_device_from_ip(ip: str, db: AsyncSession = Depends(get_db)) -> DeviceResponse:
    """Add a discovered host to the dashboard by IP."""
    # Check if already exists
    query = select(Device).where(Device.ip == ip)
    result = await db.execute(query)
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    # Create basic device
    device = Device(
        ip=ip,
        display_name=ip,
        device_type="Unbekannt",
        device_subtype="Unknown",
        is_online=True,
        first_seen=datetime.now(),
        last_seen=datetime.now()
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    
    # Trigger info refresh (Hostname, MAC, Vendor)
    # We reuse the existing logic but manually call it or just trigger it
    try:
        from app.scanner.hostname import resolve_hostname, is_ip_like
        new_hostname = await resolve_hostname(ip)
        if new_hostname:
            device.hostname = new_hostname
            if not is_ip_like(new_hostname):
                device.display_name = new_hostname.split('.')[0]
            else:
                device.display_name = ip
        else:
            device.display_name = ip
        
        from app.scanner.discovery import resolve_mac_addresses
        hosts = [{"ip": ip, "mac": None}]
        await resolve_mac_addresses(hosts)
        if hosts[0]["mac"]:
            device.mac = hosts[0]["mac"]
            device.vendor = get_vendor(device.mac)
            
        await db.commit()
        await db.refresh(device)
    except Exception as e:
        logger.error(f"Failed to auto-refresh details for new device {ip}: {e}")

    return device


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)) -> DeviceResponse:
    """Get a single device by ID."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.patch("/{device_id}", response_model=DeviceResponse)
async def update_device(
    device_id: int,
    update: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
) -> DeviceResponse:
    """Update user-editable fields of a device."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(device, field, value)

    await db.commit()
    await db.refresh(device)
    logger.info("Device %s updated: %s", device_id, update_data)
    return device


@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a device and its services."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    await db.delete(device)
    await db.commit()


@router.post("/bulk-delete", status_code=204)
async def bulk_delete_devices(device_ids: list[int], db: AsyncSession = Depends(get_db)) -> None:
    """Delete multiple devices at once."""
    from sqlalchemy import delete
    if not device_ids:
        return

    await db.execute(delete(Device).where(Device.id.in_(device_ids)))
    await db.commit()
    logger.info(f"Bulk deleted {len(device_ids)} devices")


@router.post("/{device_id}/refresh-info", response_model=DeviceResponse)
async def refresh_device_info(device_id: int, db: AsyncSession = Depends(get_db), commit: bool = True) -> DeviceResponse:
    """Trigger a manual metadata refresh (Hostname, MAC, Vendor)."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # 1. Try to resolve Hostname (FQDN)
    from app.scanner.hostname import resolve_hostname
    from app.models.setting import Setting
    
    # Get DNS server from settings
    dns_server = None
    dns_q = await db.execute(select(Setting).where(Setting.key == "dns.server"))
    dns_s = dns_q.scalar_one_or_none()
    if dns_s:
        dns_server = dns_s.value

    new_hostname = await resolve_hostname(device.ip, dns_server=dns_server)
    if new_hostname:
        device.hostname = new_hostname
        # Update display name if it's currently just an IP or generic name
        if is_ip_like(device.display_name) and not is_ip_like(new_hostname):
            # Prefer the short hostname for display
            device.display_name = new_hostname.split('.')[0]
            logger.info(f"Corrected display name for {device.ip} to {device.display_name}")
        logger.info(f"Updated hostname for {device.ip} to {new_hostname}")
    
    # 2. Try to resolve MAC via ARP if missing
    if not device.mac:
        from app.scanner.discovery import resolve_mac_addresses
        hosts = [{"ip": device.ip, "mac": None}]
        await resolve_mac_addresses(hosts)
        if hosts[0]["mac"]:
            device.mac = hosts[0]["mac"]
    
    # 3. Try to resolve Vendor via MAC
    if device.mac:
        device.vendor = get_vendor(device.mac)
    
    if commit:
        await db.commit()
        await db.refresh(device)
    return device

@router.post("/{device_id}/refresh-services", response_model=DeviceResponse)
async def refresh_device_services(device_id: int, db: AsyncSession = Depends(get_db), commit: bool = True) -> DeviceResponse:
    """Trigger a robust nmap -Pn scan for a single device to update its services."""
    from sqlalchemy.orm import selectinload
    res = await db.execute(
        select(Device)
        .where(Device.id == device_id)
        .options(selectinload(Device.services))
    )
    device = res.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    from app.scanner.port_scanner import nmap_scan
    from app.scanner.classifier import classify_device
    from app.models.setting import Setting
    
    # Get DNS server from settings
    dns_server = None
    dns_q = await db.execute(select(Setting).where(Setting.key == "dns.server"))
    dns_s = dns_q.scalar_one_or_none()
    if dns_s:
        dns_server = dns_s.value

    # 1. Run robust nmap scan
    open_ports = await nmap_scan(device.ip, dns_server=dns_server)
    
    # If nmap fails/is not installed, fall back to simple scan
    if not open_ports:
        from app.scanner.port_scanner import scan_ports
        open_ports = await scan_ports(device.ip, gentle=False, timeout=0.5)
    
    # 2. Re-classify to update metadata based on new ports
    classification = classify_device({"ip": device.ip, "ports": open_ports})
    if classification and classification.get("device_type") != "Unbekannt":
        device.device_type = classification.get("device_type")
        if not device.icon:
            device.icon = classification.get("icon")

    # 3. Update services in DB
    # Mark existing auto-detected services as down if port not found
    for svc in device.services:
        if svc.is_auto_detected:
            svc.is_up = svc.port in open_ports
            svc.last_checked = datetime.now()
    
    # 4. Add found ports. First use classification, then add anything else missing.
    found_ports_handled = set()
    
    # Process classification templates first (better names/icons)
    if classification and "services" in classification:
        for svc_data in classification["services"]:
            found_ports_handled.add(svc_data["port"])
            existing_svc = next((s for s in device.services if s.port == svc_data["port"]), None)
            if not existing_svc:
                db.add(Service(
                    device_id=device.id,
                    name=svc_data["name"],
                    protocol=svc_data["protocol"],
                    port=svc_data["port"],
                    url_template=svc_data["url_template"],
                    color=svc_data.get("color", "#34495e"),
                    is_up=True,
                    is_auto_detected=True,
                    last_checked=datetime.now()
                ))
            else:
                # Update existing
                existing_svc.is_up = True
                if existing_svc.is_auto_detected:
                    if existing_svc.name.startswith("Service "): existing_svc.name = svc_data["name"]
                    if not existing_svc.color or existing_svc.color == "#34495e": existing_svc.color = svc_data.get("color")

    # Now add ANY other port that nmap found but classification skipped
    for port in open_ports:
        if port not in found_ports_handled:
            existing_svc = next((s for s in device.services if s.port == port), None)
            if not existing_svc:
                db.add(Service(
                    device_id=device.id,
                    name=f"Service {port}",
                    protocol="tcp",
                    port=port,
                    url_template=f"http://{{ip}}:{port}",
                    color="#34495e",
                    is_up=True,
                    is_auto_detected=True,
                    last_checked=datetime.now()
                ))
            else:
                existing_svc.is_up = True

    if commit:
        await db.commit()
        await db.refresh(device)
    return device

@router.get("/{device_id}/history", response_model=list[DeviceHistoryResponse])
async def get_device_history(device_id: int, db: AsyncSession = Depends(get_db)):
    """Get the status history for a specific device."""
    from app.models.device import DeviceHistory
    result = await db.execute(
        select(DeviceHistory)
        .where(DeviceHistory.device_id == device_id)
        .order_by(DeviceHistory.timestamp.desc())
        .limit(50)
    )
    return result.scalars().all()


# --- Services ---
router_services = APIRouter(prefix="/api/services", tags=["services"])

@router.post("/{device_id}/services", response_model=ServiceResponse)
async def add_service(device_id: int, data: ServiceCreate, db: AsyncSession = Depends(get_db)):
    """Add a new service to a device."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Auto-generate url_template if empty
    url_template = data.url_template
    if not url_template:
        proto = data.protocol.lower()
        if proto in ["http", "https"]:
            url_template = f"{proto}://{{ip}}:{{port}}"
        elif proto == "ssh":
            url_template = "ssh://{ip}:{port}"
        elif proto == "smb":
            url_template = "smb://{ip}"
    
    service = Service(device_id=device_id, **data.model_dump(exclude={"url_template"}), url_template=url_template)
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return service

@router_services.patch("/{service_id}", response_model=ServiceResponse)
async def update_service(service_id: int, data: ServiceUpdate, db: AsyncSession = Depends(get_db)):
    """Update an existing service. Manually updated services are no longer 'auto_detected'."""
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    update_data = data.model_dump(exclude_unset=True)
    
    # If protocol changed but url_template is default or null, update url_template too
    if "protocol" in update_data and (not service.url_template or "{ip}" in service.url_template):
        proto = update_data["protocol"].lower()
        if proto in ["http", "https"]:
            service.url_template = f"{proto}://{{ip}}:{{port}}"
        elif proto == "ssh":
            service.url_template = "ssh://{ip}:{port}"
        elif proto == "smb":
            service.url_template = "smb://{ip}"

    for field, value in update_data.items():
        setattr(service, field, value)
    
    # Protect from future scan overwrites if any user field is modified
    service.is_auto_detected = False
    
    await db.commit()
    await db.refresh(service)
    return service

@router_services.delete("/{service_id}", status_code=204)
async def delete_service(service_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a service."""
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    await db.delete(service)
    await db.commit()


# --- Groups ---

groups_router = APIRouter(prefix="/api/groups", tags=["groups"])


@groups_router.get("", response_model=list[GroupResponse])
async def list_groups(db: AsyncSession = Depends(get_db)) -> list[GroupResponse]:
    """List all device groups with device counts."""
    result = await db.execute(select(DeviceGroup).order_by(DeviceGroup.sort_order))
    groups = result.scalars().all()

    response = []
    for group in groups:
        response.append(GroupResponse(
            id=group.id,
            name=group.name,
            icon=group.icon,
            color=group.color,
            sort_order=group.sort_order,
            is_default=group.is_default,
            device_count=len(group.devices),
        ))
    return response


@groups_router.post("", response_model=GroupResponse, status_code=201)
async def create_group(data: GroupCreate, db: AsyncSession = Depends(get_db)) -> GroupResponse:
    """Create a new device group."""
    group = DeviceGroup(**data.model_dump())
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return GroupResponse(
        id=group.id,
        name=group.name,
        icon=group.icon,
        color=group.color,
        sort_order=group.sort_order,
        is_default=group.is_default,
        device_count=0,
    )


@groups_router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: int,
    update: GroupUpdate,
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    """Update a device group."""
    group = await db.get(DeviceGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(group, field, value)

    await db.commit()
    await db.refresh(group)
    return GroupResponse(
        id=group.id,
        name=group.name,
        icon=group.icon,
        color=group.color,
        sort_order=group.sort_order,
        is_default=group.is_default,
        device_count=len(group.devices),
    )


@groups_router.delete("/{group_id}", status_code=204)
async def delete_group(group_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a device group. Devices in this group will be unassigned."""
    group = await db.get(DeviceGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    if group.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete default group")

    # The relationship will set device.group_id to null automatically if configured,
    # otherwise we do it manually. SQLAlchemy back_populates handles this.
    await db.delete(group)
    await db.commit()
