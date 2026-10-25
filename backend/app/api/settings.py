import hmac
import re
from urllib.parse import urlparse
from pydantic import RootModel
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, text
from app.database import get_db
from app.models.device import Device, Service, DeviceGroup
from app.models.setting import Setting
from app.schemas.network import normalize_dns_server
from app.scanner.subnets import merge_subnets
import logging

logger = logging.getLogger(__name__)
from app.api.auth import get_current_admin

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Credentials: never returned by GET, never written through the generic POST
# (the password has its own endpoint, POST /api/auth/password, which checks the old one)
SENSITIVE_KEYS = {"api.master_token", "api.admin_password"}

# The only keys the generic POST may write (#41). Everything else is managed by its own
# endpoint: setup.complete only by the setup wizard and the authenticated reset-db, the
# credentials by /api/auth/password. A settings:write token must not be able to put the
# server back into setup mode, where /api/setup/complete hands out a new admin password.
WRITABLE_KEYS = frozenset({
    # Settings page (React useSettingsForm, Vue SettingsView)
    "scan_interval", "quick_scan_interval", "scan_timeout", "scanner.offline_threshold",
    "scanner.health_probe_interval", "dns.server", "history_retention_days",
    "server_url_override", "server.url", "system.log_level", "ui.start_page", "ui.default_frontend",
    # Network view groups, topology flow controls, GravityUI appearance
    "network_groups", "ui.line_colors", "ui.orbit_layout", "ui.orbit_roles", "ui.link_type_colors",
    # Telemetry retention (clamped when read) and agent adoption
    "telemetry.raw_retention_hours", "telemetry.hourly_retention_days", "telemetry.daily_retention_days",
    "agent.allow_auto_adoption",
    # Legacy comma-separated subnet list, merged into the Subnet table
    "scan_subnets",
})
# Display-only settings stored under a free-form key
WRITABLE_PREFIXES = ("theme.", "topology.")


def is_writable_key(key: str) -> bool:
    """Whether POST /api/settings may write this key."""
    return key in WRITABLE_KEYS or key.startswith(WRITABLE_PREFIXES)


@router.get("", dependencies=[Depends(get_current_admin)])
async def get_all_settings(db: AsyncSession = Depends(get_db)):
    """Fetch all system settings as a key-value dictionary, excluding secrets."""
    result = await db.execute(select(Setting))
    settings = result.scalars().all()
    # Filter out sensitive keys to prevent credentials leakage (P0 security fix)
    return {s.key: s.value for s in settings if s.key not in SENSITIVE_KEYS}

SettingsUpdate = RootModel[dict[str, str]]


# server.url is embedded into the generated agent install script (run as root via
# `curl | sudo bash`), so beyond being a URL it must not carry anything a shell
# could interpret. Host part: letters, digits, dots, hyphens and the port colon only.
_SERVER_URL_NETLOC_RE = re.compile(r"^[a-zA-Z0-9.\-:]+$")
_SERVER_URL_PATH_RE = re.compile(r"^[a-zA-Z0-9._~/\-]*$")
_SHELL_SPECIAL_CHARS = frozenset("\"'`$;&|\n\r\t \\<>(){}*?!#")


def check_server_url(value: str) -> None:
    """Raise ValueError unless value is a plain http(s)://host[:port][/path] URL."""
    if any(ch in _SHELL_SPECIAL_CHARS for ch in value):
        raise ValueError("contains whitespace or shell special characters")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("scheme must be http or https")
    if not parsed.netloc or not _SERVER_URL_NETLOC_RE.match(parsed.netloc) or not parsed.hostname:
        raise ValueError("host may only contain letters, digits, dots, hyphens and a port")
    _ = parsed.port  # raises ValueError for a non-numeric or out-of-range port
    if parsed.query or parsed.fragment or parsed.params:
        raise ValueError("query strings and fragments are not allowed")
    if not _SERVER_URL_PATH_RE.match(parsed.path):
        raise ValueError("path contains unsupported characters")


def _validate_server_url(value: str) -> None:
    """Reject server URLs that are not plain HTTP(S) URLs safe to embed in the install script."""
    try:
        check_server_url(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid server URL: '{value}'. Must be a plain HTTP or HTTPS URL without query or special characters (e.g. http://192.168.1.100:8000)."
        )


def _validate_dns_server(value: str) -> None:
    """Reject DNS servers that are not a single IP address (the value is passed to nmap)."""
    try:
        normalize_dns_server(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _validate_scan_subnets(value: str) -> None:
    """Reject subnet lists containing invalid CIDR entries."""
    import ipaddress
    invalid_subnets = []
    for sub in value.split(","):
        sub = sub.strip()
        if not sub:
            continue
        try:
            ipaddress.ip_network(sub, strict=False)
        except ValueError:
            invalid_subnets.append(sub)

    if invalid_subnets:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid subnets: {', '.join(invalid_subnets)}. Please use a format like 192.168.1.0/24."
        )


def _validate_offline_threshold(value: str) -> None:
    """Reject offline thresholds that are not whole numbers between 1 and 20."""
    if not value.strip().isdigit() or not 1 <= int(value.strip()) <= 20:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid offline threshold: '{value}'. Must be a whole number between 1 and 20."
        )


def _validate_start_page(value: str) -> None:
    """Reject start page settings that are not an approved internal route."""
    if value not in ("/", "/health"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid start page: '{value}'. Must be '/' or '/health'."
        )


def _validate_default_frontend(value: str) -> None:
    """Reject a default interface other than the React UI or GravityUI."""
    if value not in ("react", "vue"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid default frontend: '{value}'. Must be 'react' or 'vue'."
        )


_VALIDATORS = {
    "server.url": _validate_server_url,
    "dns.server": _validate_dns_server,
    "scan_subnets": _validate_scan_subnets,
    "scanner.offline_threshold": _validate_offline_threshold,
    "ui.start_page": _validate_start_page,
    "ui.default_frontend": _validate_default_frontend,
}


@router.post("", dependencies=[Depends(get_current_admin)])
async def update_settings(settings: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    """Update or create system settings."""
    protected = SENSITIVE_KEYS.intersection(settings.root)
    if protected:
        raise HTTPException(
            status_code=400,
            detail=f"{', '.join(sorted(protected))} cannot be changed here. Change the password under Settings > Access.",
        )
    rejected = sorted(key for key in settings.root if not is_writable_key(key))
    if rejected:
        raise HTTPException(
            status_code=400,
            detail=f"{', '.join(rejected)} cannot be changed through /api/settings.",
        )
    for key, value in settings.root.items():
        # Validate known keys before persisting
        validator = _VALIDATORS.get(key)
        if validator and value:
            validator(value)

        if key == "scan_subnets":
            # Scan subnets live in the Subnet table (#18); older clients still send the old
            # comma-separated setting, so its entries are added there instead of stored here
            await merge_subnets(db, [s for s in value.split(",") if s.strip()])
            continue

        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.value = value
        else:
            db.add(Setting(key=key, value=value))
    
    await db.commit()
    
    # Apply log level if changed
    if "system.log_level" in settings.root:
        from app.services.log_streamer import apply_log_level
        apply_log_level(settings.root["system.log_level"])
        
    return {"status": "success"}


def _drop_runtime_credentials() -> None:
    """Forget what grants access outside the database: sessions, codes, tickets, open terminals (#48)."""
    from app.services.session_service import session_store
    from app.services.enrollment_service import enrollment_store
    from app.services.ssh_terminal import close_all_sessions
    from app.api.agent_patches import _temp_patch_tokens
    from app.api.ssh import _tickets
    from app.api.backup import invalidate_all_runtime_caches

    logged_out = session_store.delete_all_except(None)
    enrollment_store.clear()
    _temp_patch_tokens.clear()
    _tickets.clear()
    closed = close_all_sessions()
    invalidate_all_runtime_caches()
    logger.warning("Database reset: %d browser session(s) logged out, %d terminal session(s) closed", logged_out, closed)


@router.post("/reset-db", status_code=200, dependencies=[Depends(get_current_admin)])
async def reset_database(db: AsyncSession = Depends(get_db)):
    """Wipe all devices, services, and reset setup status for a fresh start."""
    try:
        import asyncio
        from app.scanner.scheduler import scheduler
        
        # Stop scheduler BEFORE deletion to avoid StaleDataError
        logger.info("Stopping scanner scheduler before data wipe...")
        try:
            await asyncio.wait_for(scheduler.stop(), timeout=5.0)
        except Exception as se:
            logger.warning(f"Scheduler stop failed/timed out: {se}")

        from app.models.device import DeviceHistory, DiscoveredHost, Device, Service, DeviceGroup
        from app.models.agent import AgentToken, DeviceMetrics, AgentConfig
        from app.models.topology import TopologyLink, Rack
        
        # 2. Wipe tables (Nuclear Option: sync_wipe with PRAGMA foreign_keys=OFF)
        logger.info("Wiping database tables...")
        
        def sync_wipe(sync_conn):
            """Synchronous wipe executed on the raw connection to bypass FK constraints."""
            sync_conn.execute(text("PRAGMA foreign_keys=OFF"))
            
            # List of tables to clear in order (Leaf to Root)
            # Using raw table names to be independent of model mapping issues
            # Credentials of the old setup go too (#48): after a reset because something leaked,
            # an old API token, webhook or stored SSH key must not work for the new setup.
            tables = [
                "api_tokens", "webhook_subscriptions",
                "ssh_history", "ssh_profiles", "ssh_known_hosts", "ssh_keys",
                "topology_links", "agent_tokens", "agent_configs", "device_interfaces",
                # Measurement data in the attached telemetry.db
                "telemetry.device_metrics", "telemetry.device_health_samples",
                "telemetry.device_health_rollups", "telemetry.device_metrics_rollups",
                "device_history", "services", "devices", "racks", "discovered_hosts",
                "subnets", "router_import_sources", "app_settings"
            ]
            
            for table in tables:
                try:
                    sync_conn.execute(text(f"DELETE FROM {table}"))
                    logger.debug(f"Table {table} wiped.")
                except Exception as te:
                    # Ignore errors for tables that might not exist yet
                    logger.debug(f"Skipping table {table}: {te}")

            # Special resets (where we don't want to delete everything)
            sync_conn.execute(text("DELETE FROM device_groups WHERE is_default = 0"))
            sync_conn.execute(text("DELETE FROM app_settings WHERE key = 'setup.complete'"))
            
            sync_conn.execute(text("PRAGMA foreign_keys=ON"))

        # Run the sync wipe in the async context
        await db.run_sync(sync_wipe)
        await db.commit()
        logger.info("Database objects deleted and changes committed.")
        _drop_runtime_credentials()
        
        # 3. Restart scheduler
        try:
            await scheduler.start()
            logger.info("Scanner scheduler restarted after database reset.")
        except Exception as se:
            logger.error(f"Failed to restart scheduler: {se}")

        logger.warning("Database reset triggered: All devices and setup status cleared.")
        return {"status": "success", "message": "Database and setup status cleared successfully"}
    except Exception as e:
        await db.rollback()
        logger.error(f"Reset failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
