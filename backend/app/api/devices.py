import asyncio
import ipaddress
import json
import logging
import re

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_admin
from app.database import get_db
from app.models.device import Device, DeviceGroup, Service
from app.models.agent import AgentToken
from app.scanner.vendor import get_vendor
from app.services.cache_service import topology_cache, dashboard_cache
from app.scanner.hostname import HOSTNAME_SOURCES, choose_hostname, lookup_dns_names, resolve_hostname, is_ip_like
from app.services.interface_service import annotate_primary_subnets, device_for_interface_ip
from app.schemas.device import (
    DeviceResponse,
    DeviceUpdate,
    DeviceHistoryResponse,
    ServiceResponse,
    ServiceCreate,
    ServiceUpdate,
    safe_url_template,
    GroupCreate,
    GroupResponse,
    GroupUpdate,
    GroupWithDevicesResponse,
)

logger = logging.getLogger(__name__)
# Auth sits on the routers themselves (defense in depth): main.py adds it again on
# include, FastAPI caches the dependency per request, so it still runs once.
# get_current_admin also accepts scoped API tokens and enforces their scopes.
router = APIRouter(prefix="/api/devices", tags=["devices"], dependencies=[Depends(get_current_admin)])


def _annotate_agent(device, token, latest_version, latest_metrics, normalize_version) -> None:
    """has_agent, has_pending_token and agent_info of a device from its agent token (None: no agent)."""
    device.has_agent = token is not None
    device.has_pending_token = token is not None and token.pending_token is not None
    if token is not None:
        device.agent_info = {
            "agent_version": normalize_version(token.agent_version),
            "latest_version": latest_version,
            "latest_metrics": latest_metrics.get(device.id),
        }


async def _dns_server(db: AsyncSession) -> str | None:
    """The DNS server set in the settings, or None for the system resolver."""
    from app.models.setting import Setting
    row = (await db.execute(select(Setting).where(Setting.key == "dns.server"))).scalar_one_or_none()
    return row.value if row else None


async def _dns_servers(db: AsyncSession) -> tuple[str | None, str | None]:
    """DNS 1 and DNS 2 from the settings; empty values count as unset."""
    from app.models.setting import Setting
    rows = (await db.execute(select(Setting).where(Setting.key.in_(("dns.server", "dns.server_secondary"))))).scalars().all()
    values = {r.key: (r.value or "").strip() or None for r in rows}
    return values.get("dns.server"), values.get("dns.server_secondary")


async def _lookup_device_hostname(dev, ip: str, servers: tuple[str | None, str | None], lookup, use_cache: bool = True) -> str | None:
    """A device's hostname. With a second DNS server both servers are asked, their answers kept on the
    device for the editor, and the one the user picked wins (`lookup` is the usual resolver chain)."""
    primary, secondary = servers
    if not secondary:
        # Answers kept from a DNS 2 that is gone would stay pickable in the editor
        dev.dns_names = None
        return await lookup(ip, dns_server=primary, use_cache=use_cache)
    # Asked side by side, so a slow or unreachable DNS 2 adds no wait to the usual lookup
    found, names = await asyncio.gather(
        lookup(ip, dns_server=primary, use_cache=use_cache), lookup_dns_names(ip, primary, secondary)
    )
    dev.dns_names = json.dumps(names)
    return choose_hostname(found, names, dev.hostname_source)


def _set_hostname_source(device, source: str | None) -> None:
    """Pin the DNS server that names the device; a pinned server that answered sets the hostname right away."""
    device.hostname_source = source if source in HOSTNAME_SOURCES else None
    if not device.hostname_source or not device.dns_names:
        return
    try:
        names = json.loads(device.dns_names)
    except ValueError:
        return
    name = names.get(device.hostname_source[-1]) if isinstance(names, dict) else None
    if name:
        _apply_hostname(device, name)


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
    # Cache check
    cache_key = f"list_devices:{include_hidden}:{group_id}"
    cached = dashboard_cache.get(cache_key)
    if cached: return cached

    result = await db.execute(query)
    devices = result.scalars().all()
    
    # Pre-populate has_agent and agent_info flags based on AgentToken existence
    # Also map parent names
    from app.api.agent import LATEST_AGENT_VERSION, _latest_metrics
    from app.version import normalize_version
    device_map = {d.id: (d.display_name or d.ip) for d in devices}

    # Batch-load agent tokens and out-of-list parent names (one query each, not one per device)
    device_ids = [d.id for d in devices]
    token_map: dict[int, AgentToken] = {}
    if device_ids:
        token_res = await db.execute(select(AgentToken).where(AgentToken.device_id.in_(device_ids)))
        token_map = {t.device_id: t for t in token_res.scalars().all()}

    # Parents outside the current list (e.g. hidden or in another group)
    missing_parent_ids = {d.parent_id for d in devices if d.parent_id and d.parent_id not in device_map}
    missing_parent_names: dict[int, str | None] = {}
    if missing_parent_ids:
        parent_res = await db.execute(
            select(Device.id, Device.display_name).where(Device.id.in_(missing_parent_ids))
        )
        missing_parent_names = {pid: name for pid, name in parent_res.all()}

    latest_version = normalize_version(LATEST_AGENT_VERSION)
    for device in devices:
        _annotate_agent(device, token_map.get(device.id), latest_version, _latest_metrics, normalize_version)
        if device.parent_id:
            device.parent_name = device_map.get(device.parent_id) or missing_parent_names.get(device.parent_id)

    await annotate_primary_subnets(db, devices)

    # Cache plain response objects: the ORM instances detach when this request's
    # session closes, and later reads of them could raise DetachedInstanceError
    responses = [DeviceResponse.model_validate(d) for d in devices]
    dashboard_cache.set(cache_key, responses)
    return responses


async def _refresh_device_metadata(dev, ip: str, mac_map: dict[str, str], servers: tuple[str | None, str | None]) -> bool:
    """Fill a missing MAC, update the vendor and the hostname; True when anything changed."""
    from app.scanner.hostname import resolve_hostname as lookup_hostname, is_ip_like as ip_like

    names_before = dev.dns_names
    changed = False
    if not dev.mac and ip in mac_map:
        dev.mac = mac_map[ip]
        changed = True
    new_vendor = get_vendor(dev.mac) if dev.mac else None
    if new_vendor and dev.vendor != new_vendor:
        dev.vendor = new_vendor
        changed = True
    new_hostname = await _lookup_device_hostname(dev, ip, servers, lookup_hostname)
    if new_hostname and dev.hostname != new_hostname:
        dev.hostname = new_hostname
        if ip_like(dev.display_name) and not ip_like(new_hostname):
            dev.display_name = new_hostname.split('.')[0]
        changed = True
    return changed or dev.dns_names != names_before


async def _bulk_metadata_refresh(devices_to_refresh, servers: tuple[str | None, str | None]) -> None:
    """Background part of refresh-all: one ARP sweep, then each device in its own session."""
    from app.database import async_session
    from app.scanner.arp import resolve_mac_addresses

    logger.info(f"Starting bulk metadata refresh for {len(devices_to_refresh)} devices.")
    hosts_for_mac = [{"ip": d.ip, "mac": None} for d in devices_to_refresh]
    await resolve_mac_addresses(hosts_for_mac)
    mac_map = {h["ip"]: h["mac"] for h in hosts_for_mac if h["mac"]}

    updated = 0
    for d_id, d_ip, _display_name in devices_to_refresh:
        try:
            async with async_session() as local_db:
                dev = await local_db.get(Device, d_id)
                if dev and await _refresh_device_metadata(dev, d_ip, mac_map, servers):
                    await local_db.commit()
                    updated += 1
        except Exception as e:
            logger.debug(f"Metadata refresh failed for {d_ip}: {e}")

    # Device rows changed in their own sessions: drop the cached lists and topology
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()
    logger.info(f"Bulk metadata refresh complete. Updated {updated} devices.")


@router.post("/refresh-all", status_code=200)
async def refresh_all_devices(background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)) -> dict:
    """Trigger a metadata refresh (DNS, MAC, Vendor) for all known devices."""
    try:
        devices_to_refresh = (await db.execute(select(Device.id, Device.ip, Device.display_name))).all()
        background_tasks.add_task(_bulk_metadata_refresh, devices_to_refresh, await _dns_servers(db))
        return {"status": "success", "message": f"Bulk metadata refresh (DNS/MAC/Vendor) started for {len(devices_to_refresh)} devices"}
    except Exception as e:
        logger.error(f"Refresh all failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add-from-ip", response_model=DeviceResponse)
async def add_device_from_ip(ip: str, db: AsyncSession = Depends(get_db)) -> DeviceResponse:
    """Add a discovered host to the dashboard by IP."""
    # The value is stored and handed to the hostname resolvers (subprocesses), so only
    # a plain IPv4 address gets past here
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid IP address format")

    # Check if already exists
    query = select(Device).where(Device.ip == ip)
    result = await db.execute(query)
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    # A router's VLAN address is already on the dashboard as an interface of its device
    owner = await device_for_interface_ip(db, ip)
    if owner:
        return owner

    # Create basic device
    device = Device(
        ip=ip,
        display_name=ip,
        device_type="Unbekannt",
        device_subtype="Unknown",
        is_online=True,
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc)
    )
    db.add(device)
    await db.flush()
    from app.models.device import DeviceHistory
    db.add(DeviceHistory(
        device_id=device.id,
        status="new_device",
        message=f"Device {device.display_name or device.ip} added to dashboard",
        read=False,
    ))
    await db.commit()
    await db.refresh(device)
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()
    
    # Look up name, MAC and vendor right away; the device stays even when that fails
    try:
        await _fill_new_device_details(device, ip)
        await db.commit()
        await db.refresh(device)
        dashboard_cache.invalidate_all()
        topology_cache.invalidate()
    except Exception as e:
        logger.error(f"Failed to auto-refresh details for new device {ip}: {e}")

    return device


async def _lookup_mac(ip: str) -> str | None:
    from app.scanner.arp import resolve_mac_addresses
    hosts = [{"ip": ip, "mac": None}]
    await resolve_mac_addresses(hosts)
    return hosts[0]["mac"]


async def _fill_new_device_details(device, ip: str) -> None:
    """Hostname and short display name (the IP when no real name answers), MAC and vendor of a new device."""
    from app.scanner.hostname import resolve_hostname as lookup_hostname, is_ip_like as ip_like

    new_hostname = await lookup_hostname(ip)
    if new_hostname:
        device.hostname = new_hostname
    device.display_name = new_hostname.split('.')[0] if new_hostname and not ip_like(new_hostname) else ip

    mac = await _lookup_mac(ip)
    if mac:
        device.mac = mac
        device.vendor = get_vendor(mac)


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)) -> DeviceResponse:
    """Get a single device by ID."""
    device = await db.get(Device, device_id)
    if not device:
        from app.exceptions import DeviceNotFoundError
        raise DeviceNotFoundError(device_id)
    await annotate_primary_subnets(db, [device])
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
    if "hostname_source" in update_data:
        _set_hostname_source(device, update_data.pop("hostname_source"))
    for field, value in update_data.items():
        setattr(device, field, value)

    if "alert_offline" in update_data:
        from app.models.setting import Setting
        marker_key = "migration.rc4_infra_alert_offline_repaired"
        existing_marker = (await db.execute(select(Setting).where(Setting.key == marker_key))).scalar_one_or_none()
        if existing_marker is None:
            db.add(Setting(key=marker_key, value="true", category="system"))

    await db.commit()
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()
    await db.refresh(device)
    logger.info("Device %s updated: %s", device_id, update_data)
    return device


async def _delete_device_dependencies(db: AsyncSession, device_ids: list[int]) -> None:
    """Safely delete all database rows referencing the given device IDs to prevent foreign key errors."""
    from sqlalchemy import delete, update
    from app.models.topology import TopologyLink
    from app.models.agent import AgentToken, AgentConfig
    from app.models.device import Device, Service, DeviceHistory, DeviceInterface
    from app.services.telemetry_store import delete_device_telemetry

    if not device_ids:
        return

    # 1. Topology links
    await db.execute(
        delete(TopologyLink).where(
            TopologyLink.source_id.in_(device_ids) | TopologyLink.target_id.in_(device_ids)
        )
    )

    # 2. Measurement data (telemetry.db has no foreign key that could cascade) and agent data
    await delete_device_telemetry(db, device_ids)
    await db.execute(delete(AgentToken).where(AgentToken.device_id.in_(device_ids)))
    await db.execute(delete(AgentConfig).where(AgentConfig.device_id.in_(device_ids)))

    # 3. Services, History and further interfaces
    await db.execute(delete(Service).where(Service.device_id.in_(device_ids)))
    await db.execute(delete(DeviceHistory).where(DeviceHistory.device_id.in_(device_ids)))
    await db.execute(delete(DeviceInterface).where(DeviceInterface.device_id.in_(device_ids)))

    # 4. Clear parent/child relationship
    await db.execute(
        update(Device)
        .where(Device.parent_id.in_(device_ids))
        .values(parent_id=None)
    )


@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a device and its services."""
    from sqlalchemy import delete
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    await _delete_device_dependencies(db, [device_id])
    await db.execute(delete(Device).where(Device.id == device_id))
    await db.commit()
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()


@router.post("/bulk-delete", status_code=204)
async def bulk_delete_devices(device_ids: list[int], db: AsyncSession = Depends(get_db)) -> None:
    """Delete multiple devices at once."""
    from sqlalchemy import delete
    if not device_ids:
        return

    await _delete_device_dependencies(db, device_ids)
    await db.execute(delete(Device).where(Device.id.in_(device_ids)))
    await db.commit()
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()
    logger.info(f"Bulk deleted {len(device_ids)} devices")


def _apply_hostname(device, new_hostname: str) -> None:
    """Store a found hostname; a device still named by its IP gets the short hostname as display name."""
    device.hostname = new_hostname
    if is_ip_like(device.display_name) and not is_ip_like(new_hostname):
        device.display_name = new_hostname.split('.')[0]
        logger.info(f"Corrected display name for {device.ip} to {device.display_name}")
    logger.info(f"Updated hostname for {device.ip} to {new_hostname}")


@router.post("/{device_id}/refresh-info", response_model=DeviceResponse)
async def refresh_device_info(device_id: int, db: AsyncSession = Depends(get_db), commit: bool = True) -> DeviceResponse:
    """Trigger a manual metadata refresh (Hostname, MAC, Vendor)."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # 1. Hostname (a user's request always looks again instead of answering from the cache)
    new_hostname = await _lookup_device_hostname(device, device.ip, await _dns_servers(db), resolve_hostname, use_cache=False)
    if new_hostname:
        _apply_hostname(device, new_hostname)

    # 2. MAC via ARP when missing, 3. vendor from the MAC
    if not device.mac:
        device.mac = await _lookup_mac(device.ip) or device.mac
    new_vendor = get_vendor(device.mac) if device.mac else None
    if new_vendor:
        device.vendor = new_vendor

    if commit:
        await db.commit()
        await db.refresh(device)
        dashboard_cache.invalidate_all()
        topology_cache.invalidate()
    return device

def _mark_auto_services(device, open_ports: list[int]) -> None:
    """Mark existing auto-detected services as up/down based on the scan result."""
    for svc in device.services:
        if svc.is_auto_detected:
            svc.is_up = svc.port in open_ports
            svc.last_checked = datetime.now(timezone.utc)


def _apply_classification_services(db, device, classification) -> set[int]:
    """Create/update services from the classification templates; returns handled ports."""
    found_ports_handled = set()
    if not (classification and "services" in classification):
        return found_ports_handled

    for svc_data in classification["services"]:
        found_ports_handled.add(svc_data["port"])
        existing_svc = next((s for s in device.services if s.port == svc_data["port"]), None)
        if existing_svc:
            _refresh_from_template(existing_svc, svc_data)
        else:
            db.add(_service_from_template(device.id, svc_data))
    return found_ports_handled


_PLACEHOLDER_COLOR = "#34495e"


def _service_from_template(device_id: int, svc_data: dict) -> Service:
    return Service(
        device_id=device_id,
        name=svc_data["name"],
        protocol=svc_data["protocol"],
        port=svc_data["port"],
        url_template=safe_url_template(svc_data["url_template"]),
        color=svc_data.get("color", _PLACEHOLDER_COLOR),
        is_up=True,
        is_auto_detected=True,
        last_checked=datetime.now(timezone.utc)
    )


def _refresh_from_template(svc: Service, svc_data: dict) -> None:
    """Mark the service up; an auto-detected one swaps a placeholder name or colour for the template's."""
    svc.is_up = True
    if not svc.is_auto_detected:
        return
    if svc.name.startswith("Service "):
        svc.name = svc_data["name"]
    if not svc.color or svc.color == _PLACEHOLDER_COLOR:
        svc.color = svc_data.get("color")


def _add_missing_services(db, device, open_ports: list[int], found_ports_handled: set[int]) -> None:
    """Add any port nmap found but classification skipped."""
    for port in open_ports:
        if port in found_ports_handled:
            continue
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
                last_checked=datetime.now(timezone.utc)
            ))
        else:
            existing_svc.is_up = True


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

    dns_server = await _dns_server(db)

    # 1. Run robust nmap scan
    open_ports = await nmap_scan(device.ip, dns_server=dns_server)
    
    # If nmap fails/is not installed, fall back to simple scan
    if not open_ports:
        from app.scanner.port_scanner import scan_ports
        open_ports = await scan_ports(device.ip, gentle=False, timeout=0.5)
    
    # 2. Re-classify to update metadata based on new ports
    classification = classify_device({"ip": device.ip, "ports": open_ports})
    # The classifier answers "unknown" when no rule matches; that must not replace a known type
    if classification and classification.get("device_type") not in ("unknown", "Unbekannt"):
        device.device_type = classification.get("device_type")
        if not device.icon:
            device.icon = classification.get("icon")

    # 3. Update services in DB
    _mark_auto_services(device, open_ports)

    # 4. Add found ports. First use classification, then add anything else missing.
    found_ports_handled = _apply_classification_services(db, device, classification)
    _add_missing_services(db, device, open_ports, found_ports_handled)

    if commit:
        await db.commit()
        await db.refresh(device)
        dashboard_cache.invalidate_all()
        topology_cache.invalidate()
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


@router.post("/{device_id}/history/read-all")
async def mark_device_history_read(device_id: int, db: AsyncSession = Depends(get_db)):
    """Mark all status history entries for a specific device as read."""
    from app.models.device import DeviceHistory
    from sqlalchemy import update
    stmt = update(DeviceHistory).where(DeviceHistory.device_id == device_id, DeviceHistory.read == False).values(read=True)
    res = await db.execute(stmt)
    await db.commit()
    return {"status": "success", "device_id": device_id, "marked_read": res.rowcount or 0}


# --- Services ---
router_services = APIRouter(prefix="/api/services", tags=["services"], dependencies=[Depends(get_current_admin)])

@router.post("/{device_id}/services", response_model=ServiceResponse)
async def add_service(device_id: int, data: ServiceCreate, db: AsyncSession = Depends(get_db)):
    """Add a new service to a device."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Auto-generate url_template if empty (an unknown protocol keeps what was sent)
    url_template = data.url_template or _default_link(data.protocol) or data.url_template

    service = Service(device_id=device_id, **data.model_dump(exclude={"url_template"}), url_template=url_template)
    db.add(service)
    await db.commit()
    await db.refresh(service)
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()
    return service

def _default_link(protocol: str) -> str | None:
    """The link GravityLAN fills in for a protocol, or None when it has none."""
    proto = protocol.lower()
    if proto in ("http", "https"):
        return f"{proto}://{{ip}}:{{port}}"
    if proto == "ssh":
        return "ssh://{ip}:{port}"
    if proto == "smb":
        return "smb://{ip}"
    return None


_GENERATED_LINK = re.compile(r"[a-z][a-z0-9+.-]*://\{ip\}(?::(\{port\}|\d+))?/?", re.IGNORECASE)


def _is_generated_link(template: str | None, port: int) -> bool:
    """True for an empty link or one GravityLAN made itself: scheme://{ip}, optionally with {port} or the service's port.

    Anything else (a path, another port, a host name) was written by the user and is kept.
    """
    if not template:
        return True
    match = _GENERATED_LINK.fullmatch(template)
    if not match:
        return False
    link_port = match.group(1)
    return link_port is None or link_port == "{port}" or link_port == str(port)


@router_services.patch("/{service_id}", response_model=ServiceResponse)
async def update_service(service_id: int, data: ServiceUpdate, db: AsyncSession = Depends(get_db)):
    """Update an existing service. Manually updated services are no longer 'auto_detected'."""
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    update_data = data.model_dump(exclude_unset=True)
    
    # If protocol changed but url_template is a generated one or null, update url_template too
    if "protocol" in update_data and _is_generated_link(service.url_template, service.port):
        service.url_template = _default_link(update_data["protocol"]) or service.url_template

    # Ignoring SSL drops the expiry shown; checking it again forces a fresh check
    if update_data.get("ignore_ssl") is True:
        service.ssl_expiry_days = None
    elif update_data.get("ignore_ssl") is False:
        service.ssl_checked_at = None

    for field, value in update_data.items():
        setattr(service, field, value)
    
    # Protect from future scan overwrites if any user field is modified
    service.is_auto_detected = False
    
    await db.commit()
    await db.refresh(service)
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()
    return service

@router_services.delete("/{service_id}", status_code=204)
async def delete_service(service_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a service."""
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    await db.delete(service)
    await db.commit()
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()


# --- Groups ---

groups_router = APIRouter(prefix="/api/groups", tags=["groups"], dependencies=[Depends(get_current_admin)])


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
    trimmed = data.name.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Group name cannot be empty")

    existing = await db.execute(select(DeviceGroup).where(DeviceGroup.name == trimmed))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A group with this name already exists")

    group_data = data.model_dump()
    group_data["name"] = trimmed
    group = DeviceGroup(**group_data)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()
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
    if "name" in update_data and update_data["name"] is not None:
        trimmed = update_data["name"].strip()
        if not trimmed:
            raise HTTPException(status_code=400, detail="Group name cannot be empty")
        update_data["name"] = trimmed

        existing = await db.execute(
            select(DeviceGroup).where(
                DeviceGroup.name == trimmed,
                DeviceGroup.id != group_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="A group with this name already exists")

    for field, value in update_data.items():
        setattr(group, field, value)

    await db.commit()
    await db.refresh(group)
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()
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
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()

@groups_router.get("/{group_id}", response_model=GroupWithDevicesResponse)
async def get_group_details(
    group_id: int,
    db: AsyncSession = Depends(get_db)
) -> GroupWithDevicesResponse:
    """Get details of a single device group including its devices."""
    from sqlalchemy.orm import selectinload
    stmt = (
        select(DeviceGroup)
        .where(DeviceGroup.id == group_id)
        .options(selectinload(DeviceGroup.devices).selectinload(Device.services))
    )
    result = await db.execute(stmt)
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
        
    # Populate agent details
    from app.api.agent import LATEST_AGENT_VERSION, _latest_metrics
    from app.version import normalize_version
    
    devices_list = []
    device_ids = [d.id for d in group.devices]
    tokens_by_device: dict[int, AgentToken] = {}
    if device_ids:
        token_q = await db.execute(select(AgentToken).where(AgentToken.device_id.in_(device_ids)))
        tokens_by_device = {t.device_id: t for t in token_q.scalars().all()}

    for d in group.devices:
        token = tokens_by_device.get(d.id)
        if token:
            d.has_agent = True
            d.has_pending_token = token.pending_token is not None
            d.agent_info = {
                "agent_version": normalize_version(token.agent_version),
                "latest_version": normalize_version(LATEST_AGENT_VERSION),
                "latest_metrics": _latest_metrics.get(d.id)
            }
        else:
            d.has_agent = False
            d.has_pending_token = False
        devices_list.append(DeviceResponse.model_validate(d))
        
    return GroupWithDevicesResponse(
        id=group.id,
        name=group.name,
        icon=group.icon,
        color=group.color,
        sort_order=group.sort_order,
        is_default=group.is_default,
        device_count=len(group.devices),
        devices=devices_list
    )
