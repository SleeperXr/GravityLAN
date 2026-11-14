"""GravityLAN FastAPI Application — Main entry point.

Serves the API backend and GravityUI, the web interface (static files under /frontend-vue/).
"""
import sys
import asyncio

# Force ProactorEventLoop on Windows to support subprocesses (Nmap)
# This MUST be done before any other imports or loop creation
if sys.platform == 'win32':
    try:
        from asyncio import WindowsProactorEventLoopPolicy
        asyncio.set_event_loop_policy(WindowsProactorEventLoopPolicy())
    except ImportError:
        pass # Fallback for older python versions

import logging
import os

from contextlib import asynccontextmanager
from pathlib import Path

import asyncio
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi import WebSocket, WebSocketDisconnect

from app.config import settings
from app.version import VERSION
from app.database import init_db
from app.exceptions import GravityLANError

logger = logging.getLogger(__name__)

# Error statuses looked for in an access line whose status is not in the record's arguments
_ERROR_MARKERS = (" 400", " 401", " 403", " 404", " 422", " 500", " 502", " 503", " 504")
# Endpoints the UI polls; their successful requests would drown the log
_POLLED_PATHS = ("/api/agent/status/", "/api/devices", "/api/groups", "/api/scanner/status", "/api/health", "/api/scanner/ws")


def _access_status(record: logging.LogRecord) -> int | None:
    """The status code of a uvicorn access record ('%s - "%s %s HTTP/%s" %d'), if its arguments carry one."""
    if not (isinstance(getattr(record, "args", None), tuple) and len(record.args) >= 5):
        return None
    try:
        return int(record.args[4])
    except (ValueError, TypeError):
        return None


# Custom filter for Uvicorn access logs to ignore polling noise (only on success)
class PollingFilter(logging.Filter):
    def filter(self, record):
        status_code = _access_status(record)
        # Never filter out warnings or errors (status >= 400)
        if status_code is not None and status_code >= 400:
            return True
        msg = record.getMessage()
        if status_code is None and any(marker in msg for marker in _ERROR_MARKERS):
            return True
        return not any(path in msg for path in _POLLED_PATHS)

def _resolve_frontend_vue_dir() -> Path:
    """Resolve the GravityUI (Vue) build directory for Docker and local layouts."""
    candidates = (
        Path("/app/static-vue"),
        Path(__file__).resolve().parent.parent.parent / "frontend-vue" / "dist",
        Path(__file__).resolve().parent.parent / "frontend-vue" / "dist",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[1]


async def _migrate_legacy_scan_subnets() -> None:
    """Fold the legacy scan_subnets setting into the Subnet table, then drop the setting.

    Up to 0.3.18 the scanners read that comma-separated setting while the network
    overview showed the Subnet table, so the two could disagree (#18). Every listed
    subnet is added, or re-enabled since the setting is what was actually scanned.
    Removing the setting afterwards keeps it from becoming a second source again and
    keeps a subnet deleted later from coming back on the next start.
    """
    from app.database import async_session
    from app.models.setting import Setting
    from app.scanner.subnets import merge_subnets
    from sqlalchemy import select

    async with async_session() as db:
        res_set = await db.execute(select(Setting).where(Setting.key == "scan_subnets"))
        legacy = res_set.scalar_one_or_none()
        if legacy is None:
            return

        entries = [s for s in (legacy.value or "").split(",") if s.strip()]
        added = await merge_subnets(db, entries, enable_existing=True)
        await db.delete(legacy)
        await db.commit()
        logger.info(
            "Migration: scan_subnets setting moved to the Subnet table (%d listed, %d added: %s)",
            len(entries), len(added), ", ".join(added) or "-",
        )


async def _ensure_default_rack() -> None:
    """Create the default 'Main Rack' when the racks table is empty."""
    from app.database import async_session
    from app.models.topology import Rack
    from sqlalchemy import select

    async with async_session() as db:
        res_rack = await db.execute(select(Rack))
        if res_rack.scalars().first():
            return
        logger.info("Database: Creating default 'Main Rack'...")
        default_rack = Rack(name="Main Rack", units=42)
        db.add(default_rack)
        await db.commit()


def _configure_logging() -> None:
    """Correlation-id formatting, quieter libraries, the access-log filters and the live log stream."""
    from app.services.enrollment_service import EnrollmentCodeLogFilter
    from app.services.log_streamer import CorrelationIdFilter, SafeCorrelationIdFormatter, log_handler

    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
    # A safe formatter on every root handler prevents KeyError during child logger propagation
    formatter = SafeCorrelationIdFormatter("%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)
    logging.getLogger().addFilter(CorrelationIdFilter())

    # Aggressively suppress noisy logs; outside debug also paramiko's transport layer
    noisy = ["aiosqlite", "paramiko", "sqlalchemy.engine"] + ([] if settings.debug else ["paramiko.transport"])
    for name in noisy:
        logging.getLogger(name).setLevel(logging.WARNING)

    access = logging.getLogger("uvicorn.access")
    access.addFilter(PollingFilter())
    access.addFilter(EnrollmentCodeLogFilter())
    access.setLevel(logging.INFO)

    logging.getLogger().addHandler(log_handler)


async def _apply_saved_log_level() -> None:
    """The log level chosen under Settings (``system.log_level``); best effort, the default stays otherwise."""
    try:
        from app.database import async_session
        from app.models.setting import Setting
        from app.services.log_streamer import apply_log_level
        from sqlalchemy import select
        async with async_session() as db:
            res = await db.execute(select(Setting).where(Setting.key == "system.log_level"))
            lvl_setting = res.scalar_one_or_none()
            if lvl_setting and lvl_setting.value:
                apply_log_level(lvl_setting.value)
    except Exception:
        pass


def _ensure_writable_data_dir() -> None:
    """Create the data directory and prove it is writable; a clear message on how to fix it otherwise."""
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        test_file = settings.data_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
    except PermissionError as e:
        from app.config import process_ids
        uid, gid = process_ids()
        message = (
            f"PERMISSION ERROR: Cannot write to data directory '{settings.data_dir}' as UID {uid} / GID {gid}. "
            f"Make the host directory of the volume writable, e.g. 'chown -R {uid}:{gid} ./data' "
            f"(Unraid: 'chown -R {uid}:{gid} /mnt/user/appdata/gravitylan'), "
            "or start the container as root with PUID/PGID set to the owner of that directory."
        )
        logger.critical(message)
        raise RuntimeError(message) from e
    except Exception as e:
        logger.critical("Failed to initialize data directory '%s': %s", settings.data_dir, e)
        raise RuntimeError(f"Failed to initialize data directory '{settings.data_dir}': {e}") from e


def _register_models() -> None:
    """Import every model so init_db creates all tables."""
    from app.models.device import Device, DeviceGroup, Service, DeviceHistory, DiscoveredHost  # noqa: F401
    from app.models.topology import Rack, TopologyLink  # noqa: F401
    from app.models.network import Subnet  # noqa: F401
    from app.models.setting import Setting  # noqa: F401
    from app.models.agent import AgentToken, DeviceMetrics, AgentConfig  # noqa: F401
    from app.models.api_token import ApiToken  # noqa: F401
    from app.models.webhook import WebhookSubscription, NotificationOutbox  # noqa: F401
    from app.models.ssh import SshKey, SshProfile, SshKnownHost  # noqa: F401
    from app.models.router_import import RouterImportSource  # noqa: F401
    from app.models.audit import AuditEvent  # noqa: F401


def _backup_before_upgrade() -> None:
    """Copy the SQLite inventory before this version migrates it; an external database is the operator's."""
    if settings.database_url:
        return
    from app.database.upgrade_backup import backup_before_upgrade
    backup_before_upgrade(settings.data_dir, settings.data_dir / "gravitylan.db", settings.app_version)


def _remember_migrated_version() -> None:
    if settings.database_url:
        return
    from app.database.upgrade_backup import remember_version
    remember_version(settings.data_dir, settings.app_version)


async def _run_startup_migrations() -> None:
    """Schema migrations, the telemetry move, legacy scan subnets and the subnet cleanup, in this order."""
    from app.api.network import cleanup_invalid_subnets
    from app.database import async_session, engine
    from app.database.migrations import run_migrations
    from app.services.telemetry_store import migrate_legacy_telemetry, vacuum_inventory

    async with async_session() as db:
        await run_migrations(db)

    # Measurement tables of older versions move from the inventory into telemetry.db
    try:
        async with async_session() as db:
            moved = await migrate_legacy_telemetry(db)
        if moved:
            await vacuum_inventory(engine)
    except Exception as e:
        logger.error("Telemetry migration failed (retried on next start): %s", e, exc_info=True)

    # Fold scan_subnets into the Subnet table before the scheduler reads it
    await _migrate_legacy_scan_subnets()
    # Cleanup any invalid or ghost subnets
    await cleanup_invalid_subnets()


async def _shutdown(app: FastAPI) -> None:
    """Stop the scheduler and cancel the background tasks registered on app.state."""
    from app.scanner.scheduler import scheduler
    await scheduler.stop()

    if hasattr(app.state, "background_tasks"):
        tasks = list(app.state.background_tasks)
        logger.info("Canceling %d background tasks...", len(tasks))
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # Deliveries still running get a moment to finish before their shared HTTP client is closed
    from app.services.webhook_service import close_webhook_client, drain_webhook_tasks
    await drain_webhook_tasks()
    await close_webhook_client()

    logger.info("GravityLAN shutting down.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager — runs on startup and shutdown."""
    _configure_logging()
    await _apply_saved_log_level()

    loop = asyncio.get_running_loop()
    logger.info("GravityLAN v%s starting (Loop: %s, Timeout: %ss)...",
                settings.app_version, loop.__class__.__name__, settings.scan_timeout)

    _ensure_writable_data_dir()
    # Before init_db: creating new tables is already a change to the schema
    _backup_before_upgrade()
    _register_models()
    await init_db()
    logger.info("Database initialized: %s", settings.effective_database_url)

    # Background tasks are registered on app.state to allow a clean shutdown
    app.state.background_tasks = set()

    await _run_startup_migrations()
    _remember_migrated_version()

    from app.scanner.scheduler import scheduler
    await scheduler.start()
    await _ensure_default_rack()

    yield

    await _shutdown(app)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# --- Exception Handlers ---

from app.services.log_streamer import correlation_id_ctx
import uuid

@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    # Retrieve X-Correlation-ID from request headers, or generate a new UUID
    cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    token = correlation_id_ctx.set(cid)
    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response
    finally:
        correlation_id_ctx.reset(token)

@app.exception_handler(GravityLANError)
async def gravitylan_exception_handler(request: Request, exc: GravityLANError):
    """Handle custom application exceptions."""
    cid = correlation_id_ctx.get()
    logger.error("App Error on %s: %s", request.url.path, exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        headers={"X-Correlation-ID": cid},
        content={
            "status": "error",
            "message": exc.message,
            "type": exc.__class__.__name__,
            "correlation_id": cid
        },
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handle validation errors (422) with detailed logging.
    
    NOTE: This uses a deliberate different response schema ("status": "validation_error" 
    and "detail": list of errors) compared to standard application errors 
    ("status": "error" and "message": string) to provide compatible structure for FastAPI clients.
    """
    cid = correlation_id_ctx.get()
    logger.error("Validation error on %s: %s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        headers={"X-Correlation-ID": cid},
        content={
            "status": "validation_error",
            # jsonable_encoder: a field_validator's ValueError sits in ctx["error"] and is
            # not JSON serializable, which turned every such 422 into a 500
            "detail": jsonable_encoder(exc.errors()),
            "correlation_id": cid
        },
    )

@app.exception_handler(Exception)
async def universal_exception_handler(request: Request, exc: Exception):
    """Catch-all for any unhandled exceptions to prevent leaking server details."""
    cid = correlation_id_ctx.get()
    logger.critical("Unhandled exception on %s: %s", request.url.path, str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        headers={"X-Correlation-ID": cid},
        content={
            "status": "error",
            "message": "An unexpected internal server error occurred.",
            "correlation_id": cid
        },
    )

# CORS for development (Vite dev server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Register API routers ---
from app.api.auth import router as auth_router  # noqa: E402
from app.api.devices import groups_router, router_services, router as devices_router  # noqa: E402
from app.api.scanner import router as scanner_router  # noqa: E402
from app.api.settings import router as settings_router  # noqa: E402
from app.api.setup import router as setup_router  # noqa: E402
from app.api.agent import router as agent_router  # noqa: E402
from app.api.backup import router as backup_router  # noqa: E402
from app.api.network import router as network_router  # noqa: E402
from app.api.topology import router as topology_router  # noqa: E402
from app.api.webhooks import router as webhooks_router  # noqa: E402
from app.api.audit import router as audit_router  # noqa: E402
from app.api.summary import router as summary_router, issues_router  # noqa: E402
from app.api.logs import router as logs_router  # noqa: E402
from app.api.agents import router as agents_router  # noqa: E402
from app.api.notifications import router as notifications_router  # noqa: E402
from app.api.health import router as health_router  # noqa: E402
from app.api.ssh import router as ssh_router, ws_router as ssh_ws_router  # noqa: E402
from app.api.interfaces import router as interfaces_router  # noqa: E402
from app.api.rack_cabling import router as rack_cabling_router  # noqa: E402
from app.api.router_import import router as router_import_router  # noqa: E402
from app.api.telemetry import router as telemetry_router  # noqa: E402
from app.api.proxmox import router as proxmox_router  # noqa: E402

from app.api.auth import get_current_admin

app.include_router(auth_router)
app.include_router(backup_router, dependencies=[Depends(get_current_admin)])
app.include_router(network_router, dependencies=[Depends(get_current_admin)])
app.include_router(router_import_router, dependencies=[Depends(get_current_admin)])
app.include_router(topology_router, dependencies=[Depends(get_current_admin)])
app.include_router(rack_cabling_router, dependencies=[Depends(get_current_admin)])
app.include_router(devices_router, dependencies=[Depends(get_current_admin)])
app.include_router(interfaces_router, dependencies=[Depends(get_current_admin)])
app.include_router(groups_router, dependencies=[Depends(get_current_admin)])
app.include_router(router_services, dependencies=[Depends(get_current_admin)])
app.include_router(scanner_router, dependencies=[Depends(get_current_admin)])
app.include_router(settings_router, dependencies=[Depends(get_current_admin)])
app.include_router(telemetry_router)  # Settings > Measurement data; guards itself with get_current_admin
app.include_router(proxmox_router)  # Settings > Proxmox VE; guards itself with get_current_admin
app.include_router(webhooks_router, dependencies=[Depends(get_current_admin)])
app.include_router(audit_router, dependencies=[Depends(get_current_admin)])
app.include_router(summary_router, dependencies=[Depends(get_current_admin)])
app.include_router(issues_router, dependencies=[Depends(get_current_admin)])
app.include_router(logs_router, dependencies=[Depends(get_current_admin)])
app.include_router(agents_router, dependencies=[Depends(get_current_admin)])
app.include_router(notifications_router, dependencies=[Depends(get_current_admin)])
app.include_router(health_router, dependencies=[Depends(get_current_admin)])
app.include_router(ssh_router, dependencies=[Depends(get_current_admin)])
app.include_router(ssh_ws_router)  # Terminal WebSocket authenticates itself (browser sessions only)
app.include_router(setup_router) # Setup manages its own logic
app.include_router(agent_router) # Contains both public report and protected metrics (internally handled)
logger.info("Registered Agent API routes under /api/agent")


@app.get("/api/health")
async def health_check() -> dict:
    """Health check endpoint for Docker and monitoring."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "build": settings.build,
        "app": settings.app_name,
    }


@app.websocket("/api/logs/ws")
async def logs_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time backend log streaming with authentication."""
    from app.api.auth import authenticate_websocket_authorized

    # Logs are strictly restricted to browser-sessions, master tokens, legacy master tokens, or API tokens
    auth_info = await authenticate_websocket_authorized(
        websocket, endpoint_type="logs",
        allowed_levels=("session", "master", "master_legacy", "api_token"),
    )
    if not auth_info:
        return

    from app.services.log_streamer import log_handler
    await websocket.accept()
    
    # Send history first
    for msg in log_handler.get_history():
        await websocket.send_text(msg)
    
    log_handler.subscribe(websocket)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        log_handler.unsubscribe(websocket)
    except Exception:
        log_handler.unsubscribe(websocket)


# --- Serve GravityUI (production) ---
# index.html must be revalidated on every load: it names the hashed JS bundles,
# and a heuristically cached copy keeps serving the previous release's UI after
# an update (the version label still looks new because it comes from the API).
INDEX_HEADERS = {"Cache-Control": "no-cache"}
GRAVITYUI_PATH = "/frontend-vue/"


@app.get("/")
async def root():
    """Root endpoint: GravityUI, else status JSON.

    GravityUI is built for /frontend-vue/, so it is reached by a redirect rather than served here.
    The `?ui=` switch and the `gl_ui` cookie of the former classic view no longer matter.
    """
    if (_resolve_frontend_vue_dir() / "index.html").exists():
        return RedirectResponse(GRAVITYUI_PATH, status_code=307)
    return {
        "app": "GravityLAN",
        "version": VERSION,
        "status": "online",
        "api_docs": "/docs",
        "message": "Backend is running. GravityUI build missing in /app/static-vue."
    }


def _reject_unsafe_path(full_path: str) -> None:
    """Refuse parent references, backslashes and absolute paths before touching the disk."""
    if ".." in full_path or "\\" in full_path or full_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")


def _file_in_build(build_dir: Path, full_path: str) -> tuple[str, str | None]:
    """(real build folder, the requested file inside it or None when there is no such file); 400 when it points outside.

    realpath + startswith is the traversal check CodeQL recognises; commonpath also rejects
    siblings sharing the prefix, e.g. /app/static_other.
    """
    try:
        base_dir = os.path.realpath(str(build_dir))
        resolved_path = os.path.realpath(os.path.join(base_dir, full_path))
        if not resolved_path.startswith(base_dir) or os.path.commonpath([base_dir, resolved_path]) != base_dir:
            raise HTTPException(status_code=400, detail="Invalid path")
        return base_dir, (resolved_path if os.path.isfile(resolved_path) else None)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")


def _build_file_response(path: str) -> FileResponse:
    # index.html names the hashed bundles, so it must be revalidated on every load
    headers = INDEX_HEADERS if os.path.basename(path) == "index.html" else None
    return FileResponse(path, headers=headers)


@app.get("/frontend-vue")
@app.get("/frontend-vue/")
async def serve_vue_root():
    """Serve GravityUI (Vue + shadcn-vue) entry point."""
    vue_dir = _resolve_frontend_vue_dir()
    index_file = vue_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), headers=INDEX_HEADERS)
    raise HTTPException(status_code=404, detail="GravityUI build not found in frontend-vue/dist")


@app.get("/frontend-vue/{full_path:path}")
async def serve_vue_spa(full_path: str):
    """Serve assets or SPA fallback for GravityUI under /frontend-vue/."""
    _reject_unsafe_path(full_path)
    vue_dir = _resolve_frontend_vue_dir()
    if not vue_dir.exists():
        raise HTTPException(status_code=404, detail="GravityUI build not found")

    base_dir, file_path = _file_in_build(vue_dir, full_path)
    if file_path:
        return _build_file_response(file_path)
    index_file = os.path.realpath(os.path.join(base_dir, "index.html"))
    if os.path.isfile(index_file):
        return FileResponse(index_file, headers=INDEX_HEADERS)
    raise HTTPException(status_code=404, detail="GravityUI index.html not found")


async def redirect_to_gravityui(full_path: str):
    """Old addresses of the classic view (bookmarks such as /devices) open GravityUI; unknown API paths stay 404."""
    _reject_unsafe_path(full_path)
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    return RedirectResponse(GRAVITYUI_PATH, status_code=307)


if _resolve_frontend_vue_dir().exists():
    # Registered last, so every API route, /docs and the GravityUI routes above win
    app.get("/{full_path:path}")(redirect_to_gravityui)
    logger.info("Serving GravityUI from: %s", _resolve_frontend_vue_dir())
