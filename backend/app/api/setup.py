"""Setup wizard API — checks setup state and provides initial configuration."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.device import Device
from app.models.setting import Setting
from app.config import settings
from app.version import VERSION
from app.services.agent_deployer import get_latest_agent_version

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

    is_complete = setting is not None and setting.value == "true"
    device_count_val = device_count

    res = {
        "is_setup_complete": is_complete,
        "device_count": device_count_val,
        "version": VERSION,
        "build": settings.build,
        # Shown on the About page; the agent has its own version (it only changes with agent/)
        "agent_version": get_latest_agent_version(),
    }
    return res


import ipaddress

from pydantic import BaseModel, Field, field_validator

from app.schemas.network import normalize_dns_server
from app.schemas.device import safe_url_template

MAX_SETUP_SUBNETS = 64


class SetupCompleteRequest(BaseModel):
    dns_server: str | None = None
    admin_password: str | None = None
    # Subnets the wizard scanned. Their hosts are adopted even when the subnet is routed
    # (another VLAN) and therefore not bound to a local interface.
    subnets: list[str] | None = Field(default=None, max_length=MAX_SETUP_SUBNETS)
    # The wizard restored a backup instead of scanning: its subnets and devices stay as they are
    restored: bool = False

    @field_validator("dns_server")
    @classmethod
    def validate_dns_server(cls, v: str | None) -> str | None:
        # Goes to nmap --dns-servers and dnspython; empty means "no custom DNS"
        return normalize_dns_server(v)

    @field_validator("subnets")
    @classmethod
    def validate_subnets(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [str(ipaddress.ip_network(cidr.strip(), strict=False)) for cidr in v]


def _adoption_networks(requested: list[str] | None, local_subnets) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Networks whose hosts the wizard may adopt: the scanned subnets, else the detected local ones.

    get_local_subnets() already prefers physical interfaces and only falls back to virtual
    ones when nothing else exists (Docker bridge mode), so that list is used unfiltered.
    """
    cidrs = requested or [s.subnet for s in local_subnets]
    return [ipaddress.ip_network(cidr, strict=False) for cidr in cidrs]


def _in_adoption_networks(host, networks) -> bool:
    """Return True when the host IP belongs to one of the allowed adoption networks."""
    try:
        ip_obj = ipaddress.ip_address(host.ip)
    except ValueError:
        return False
    return any(ip_obj in net for net in networks)


def _resolve_display_name(host, current_hostname: str | None) -> str:
    """Determine the display name from hostname (domain stripped), custom name, or IP."""
    from app.scanner.hostname import is_ip_like

    if current_hostname and not is_ip_like(current_hostname):
        return current_hostname.split(".")[0]
    if host.custom_name:
        return host.custom_name
    return host.ip


def _build_detected_services(classified: dict) -> list:
    """Build Service model instances for auto-detected services."""
    from app.models.device import Service

    return [
        Service(
            name=svc_data["name"],
            protocol=svc_data["protocol"],
            port=svc_data["port"],
            url_template=safe_url_template(svc_data["url_template"]),
            color=svc_data.get("color"),
            is_auto_detected=True,
            is_up=True,
        )
        for svc_data in classified.get("services", [])
    ]


async def _ensure_hostname(host, dns_server: str | None) -> str | None:
    """Resolve the host's name when missing or IP-like, updating host.hostname in place."""
    from app.scanner.hostname import is_ip_like, resolve_hostname

    current_hostname = host.hostname
    if is_ip_like(current_hostname):
        new_hname = await resolve_hostname(host.ip, timeout=1.5, dns_server=dns_server)
        if new_hname:
            current_hostname = new_hname
            host.hostname = new_hname
    return current_hostname


async def _process_discovered_host(host, group_map, existing_ips, adoption_networks, dns_server):
    """Classify and package one discovered host into a (device, services, host) tuple or None."""
    from app.models.device import Device
    from app.scanner.classifier import classify_device
    from app.scanner.port_scanner import DEFAULT_SCAN_PORTS, scan_ports
    from app.scanner.utils import GROUP_TYPE_MAP

    if not _in_adoption_networks(host, adoption_networks):
        logger.debug(f"Setup: Skipping {host.ip} - outside the scanned networks.")
        return None

    if host.ip in existing_ips:
        return None

    # Full discovery of key ports for better classification
    found_ports = await scan_ports(host.ip, ports=DEFAULT_SCAN_PORTS, timeout=0.4)
    current_hostname = await _ensure_hostname(host, dns_server)

    classified = classify_device({
        "ip": host.ip,
        "hostname": current_hostname,
        "mac": host.mac,
        "ports": found_ports,
    }) or {"device_type": "unknown", "device_subtype": "Unknown", "services": []}

    services = _build_detected_services(classified)
    # CRITICAL: Only add device if it has at least one service
    if not services:
        logger.info(f"Setup: Skipping auto-adoption for {host.ip} (No services found)")
        return None

    device_type = classified.get("device_type", "unknown")
    group_name = GROUP_TYPE_MAP.get(device_type, "Newly discovered")
    group_id = group_map.get(group_name, group_map.get("Newly discovered"))
    display_name = _resolve_display_name(host, current_hostname)

    device = Device(
        ip=host.ip, mac=host.mac, hostname=current_hostname, display_name=display_name,
        device_type=device_type, device_subtype=classified.get("device_subtype", "Unknown"),
        vendor=host.vendor, group_id=group_id, is_online=True,
    )
    return (device, services, host)


async def _register_scan_subnets(db, requested: list[str] | None, local_subnets) -> list[str]:
    """Write the networks the wizard scanned into the Subnet table; returns the added ones.

    That table decides what the scheduler scans and which tabs the network overview
    shows. Without a scan (step skipped) the detected physical subnets are registered.
    Subnets of a local interface are named after it.
    """
    from app.scanner.subnets import merge_subnets
    names = {net.subnet: net.interface_name for net in local_subnets}
    cidrs = requested or [net.subnet for net in local_subnets if not net.is_virtual]
    added = await merge_subnets(db, cidrs, names=names)
    if added:
        logger.info("Setup: registered scan subnets %s", ", ".join(added))
    return added


async def _adopt_discovered_hosts(db, dns_server: str | None, subnets: list[str] | None) -> int:
    """Add the discovered online hosts of the scanned networks to the dashboard; returns the count."""
    import asyncio
    from app.models.device import DiscoveredHost, Device
    from app.scanner.utils import ensure_default_groups, get_local_subnets

    host_result = await db.execute(select(DiscoveredHost).where(DiscoveredHost.is_online == True))
    discovered_hosts = host_result.scalars().all()
    if not discovered_hosts:
        return 0

    group_map = await ensure_default_groups(db, commit=False)
    local_subnets = get_local_subnets()
    adoption_networks = _adoption_networks(subnets, local_subnets)

    # Avoid IP duplicates
    existing_res = await db.execute(select(Device.ip))
    existing_ips = set(existing_res.scalars().all())

    # Process all hosts in parallel
    tasks = [_process_discovered_host(h, group_map, existing_ips, adoption_networks, dns_server) for h in discovered_hosts]
    results = [res for res in await asyncio.gather(*tasks) if res]

    # 3. Process hosts
    for device, services, host in results:
        db.add(device)
        await db.flush()
        for svc in services:
            svc.device_id = device.id
            db.add(svc)

        # Update discovered host status
        host.is_monitored = True
        db.add(host)

    return len(results)


async def _setup_done(db: AsyncSession) -> bool:
    from app.models.setting import Setting
    row = (await db.execute(select(Setting).where(Setting.key == "setup.complete"))).scalar_one_or_none()
    return row is not None and row.value == "true"


@router.post("/restore")
async def restore_during_setup(http_request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> dict:
    """First start: bring back a backup instead of scanning (GravityUI setup wizard).

    Open without a login, like the rest of the wizard, and only until the setup is completed;
    afterwards backups go through /api/backup/import with a password confirmation. The backup
    never carries the admin password, the master token or the setup state: the wizard sets the
    password next, and completing it with ``restored`` keeps the restored subnets and devices.
    """
    if await _setup_done(db):
        raise HTTPException(status_code=403, detail="Setup already completed. Restore backups under Settings.")
    from app.api.backup import restore_upload
    return await restore_upload(http_request, file, db, actor="setup")


async def _upsert_setting(
    db: AsyncSession,
    key: str,
    value: str,
    *,
    category: str | None = None,
    description: str | None = None,
) -> None:
    """Create or update a Setting row."""
    row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value, category=category, description=description))


async def _insert_setting_if_missing(
    db: AsyncSession,
    key: str,
    value: str,
    *,
    category: str | None = None,
) -> bool:
    """Insert a Setting row only when no row with that key exists; returns True if inserted."""
    row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    if row:
        return False
    db.add(Setting(key=key, value=value, category=category))
    return True


async def _persist_initial_setup_settings(db: AsyncSession, request: SetupCompleteRequest) -> None:
    """Persist DNS server, admin password, setup.complete flag, and master API token."""
    import secrets
    from app.services.auth_service import hash_password

    if request.dns_server:
        await _upsert_setting(
            db,
            "dns.server",
            request.dns_server,
            category="scan",
            description="Custom DNS server for hostname resolution",
        )
        await db.flush()

    if request.admin_password:
        await _upsert_setting(
            db,
            "api.admin_password",
            hash_password(request.admin_password),
            category="system",
            description="Administrator password for dashboard login",
        )
        await db.flush()

    await _upsert_setting(db, "setup.complete", "true", category="system")
    if request.restored:
        await _insert_setting_if_missing(db, "scanner.initial_scan_done", "true", category="scan")

    if await _insert_setting_if_missing(db, "api.master_token", secrets.token_hex(32)):
        logger.info("Setup: Initializing secure Master API Token (masked for security).")

    # Commit basic settings and token now so the user can login even if migration takes long
    await db.commit()


async def _finalize_scanned_setup(db: AsyncSession, request: SetupCompleteRequest) -> int:
    """Best-effort registration of scanned subnets and adoption of discovered hosts."""
    try:
        from app.scanner.utils import get_local_subnets
        await _register_scan_subnets(db, request.subnets, get_local_subnets())
        await db.commit()
    except Exception:
        logger.exception("Setup: registering the scan subnets failed; they can be added under Settings")
        await db.rollback()

    try:
        adopted = await _adopt_discovered_hosts(db, request.dns_server, request.subnets)
        if adopted > 0:
            await _insert_setting_if_missing(db, "scanner.initial_scan_done", "true", category="scan")
        await db.commit()
        return adopted
    except Exception:
        logger.exception("Setup: adopting discovered hosts failed; settings are saved, devices can be added later")
        await db.rollback()
        return 0


@router.post("/complete")
async def mark_setup_complete(
    request: SetupCompleteRequest,
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark the initial setup as completed, sign the admin in and adopt discovered hosts."""
    logger.info(f"mark_setup_complete called: has_password={request.admin_password is not None}")

    # 0. Idempotency check: don't allow setup to run again if already complete
    if await _setup_done(db):
        raise HTTPException(status_code=400, detail="Setup already completed. Use Settings UI to change configuration.")

    await _persist_initial_setup_settings(db, request)

    # Sign the admin in right away: the wizard ends in the dashboard without a second login request
    if request.admin_password:
        from app.api.auth import issue_session_cookie
        issue_session_cookie(response, http_request.headers.get("user-agent"))

    # Register the scanned networks as scan subnets (one overview tab each), then add the
    # discovered online hosts to the dashboard. Both are best-effort: settings are already
    # committed, so a failure here must not turn into a 500 (the session cookie would be lost
    # and a retry ends in "Setup already completed").
    if request.restored:
        # The backup brought its own subnets and devices; nothing was scanned to adopt
        return {"status": "ok", "devices_adopted": 0}

    adopted = await _finalize_scanned_setup(db, request)
    return {"status": "ok", "devices_adopted": adopted}
