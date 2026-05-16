"""GravityLAN FastAPI Application — Main entry point.

Serves both the API backend and the React frontend (static files).
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
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi import WebSocket, WebSocketDisconnect

from app.config import settings
from app.version import VERSION
from app.database import init_db
from app.exceptions import GravityLANError

logger = logging.getLogger(__name__)

# Custom filter for Uvicorn access logs to ignore polling noise (only on success)
class PollingFilter(logging.Filter):
    def filter(self, record):
        status_code = None
        if hasattr(record, "args") and isinstance(record.args, tuple) and len(record.args) >= 5:
            try:
                status_code = int(record.args[4])
            except (ValueError, TypeError):
                pass

        # Never filter out warnings or errors (status >= 400)
        if status_code is not None and status_code >= 400:
            return True

        msg = record.getMessage()
        # Fallback parse check from formatted message
        if status_code is None:
            if any(err_status in msg for err_status in [" 400", " 401", " 403", " 404", " 422", " 500", " 502", " 503", " 504"]):
                return True

        if any(x in msg for x in ["/api/agent/status/", "/api/devices", "/api/groups", "/api/scanner/status", "/api/health", "/api/scanner/ws"]):
            return False
        return True

# Detection: Use /app/static in Docker, fallback to local dist for development
FRONTEND_DIR = Path("/app/static") if Path("/app/static").exists() else Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager — runs on startup and shutdown."""
    # Startup
    from app.services.log_streamer import CorrelationIdFilter, SafeCorrelationIdFormatter
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
    
    # Configure safe formatter on all root handlers to prevent KeyError during child logger propagation
    formatter = SafeCorrelationIdFormatter("%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)
        
    logging.getLogger().addFilter(CorrelationIdFilter())

    # Aggressively suppress noisy logs
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # If not in debug, also suppress the transport layer specifically
    if not settings.debug:
        logging.getLogger("paramiko.transport").setLevel(logging.WARNING)



    logging.getLogger("uvicorn.access").addFilter(PollingFilter())
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    # Attach Live Log Streamer
    from app.services.log_streamer import log_handler
    logging.getLogger().addHandler(log_handler)
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

    loop = asyncio.get_running_loop()
    logger.info("GravityLAN v%s starting (Loop: %s, Timeout: %ss)...", 
                settings.app_version, loop.__class__.__name__, settings.scan_timeout)

    # Ensure data directory exists and is writable
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        # Test write permission by creating a temporary file
        test_file = settings.data_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
    except PermissionError as e:
        logger.critical(
            "PERMISSION ERROR: Cannot write to data directory '%s'. "
            "If using Docker, ensure the volume has correct permissions (e.g., chown -R 1000:1000 ./data on the host).",
            settings.data_dir
        )
        raise RuntimeError(
            f"PERMISSION ERROR: Cannot write to data directory '{settings.data_dir}'. "
            "If using Docker, ensure the volume has correct permissions (e.g., chown -R 1000:1000 ./data on the host)."
        ) from e
    except Exception as e:
        logger.critical("Failed to initialize data directory '%s': %s", settings.data_dir, e)
        raise RuntimeError(f"Failed to initialize data directory '{settings.data_dir}': {e}") from e

    # Ensure models are imported for metadata creation
    from app.models.device import Device, DeviceGroup, Service, DeviceHistory, DiscoveredHost
    from app.models.topology import Rack, TopologyLink
    from app.models.network import Subnet
    from app.models.setting import Setting
    from app.models.agent import AgentToken, DeviceMetrics, AgentConfig

    # Initialize database tables
    await init_db()
    logger.info("Database initialized: %s", settings.effective_database_url)

    # Start Background Tasks (registered on app.state to allow clean shutdown)
    app.state.background_tasks = set()
    prune_task = asyncio.create_task(prune_metrics_loop())
    app.state.background_tasks.add(prune_task)
    prune_task.add_done_callback(app.state.background_tasks.discard)

    # --- Schema Migration ---
    from app.database.migrations import run_migrations
    from app.database import async_session
    async with async_session() as db:
        await run_migrations(db)

    # Start the scan scheduler
    from app.scanner.scheduler import scheduler
    await scheduler.start()

    # Migration: Move scan_subnets from settings to Subnet table
    async with async_session() as db:
        res_sub_count = await db.execute(select(Subnet))
        if not res_sub_count.scalars().first():
            res_set = await db.execute(select(Setting).where(Setting.key == "scan_subnets"))
            s_set = res_set.scalar_one_or_none()
            if s_set and s_set.value:
                logger.info("Migration: Found legacy scan_subnets, moving to Subnet table...")
                sub_list = [s.strip() for s in s_set.value.split(",") if s.strip()]
                for s in sub_list:
                    cidr = s
                    if "/" not in cidr:
                        if cidr.count(".") == 2: cidr = f"{cidr}.0/24"
                        else: cidr = f"{cidr}/24"
                    
                    check_existing = await db.execute(select(Subnet).where(Subnet.cidr == cidr))
                    if not check_existing.scalar_one_or_none():
                        new_sub = Subnet(cidr=cidr, name=f"Network {cidr}", is_enabled=True)
                        db.add(new_sub)
                await db.commit()

        # Create default rack if empty
        res_rack = await db.execute(select(Rack))
        if not res_rack.scalars().first():
            logger.info("Database: Creating default 'Main Rack'...")
            default_rack = Rack(name="Main Rack", units=42)
            db.add(default_rack)
            await db.commit()

    yield

    # Shutdown
    from app.scanner.scheduler import scheduler
    await scheduler.stop()

    # Cancel all registered background tasks
    if hasattr(app.state, "background_tasks"):
        tasks = list(app.state.background_tasks)
        logger.info("Canceling %d background tasks...", len(tasks))
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("GravityLAN shutting down.")


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
            "detail": exc.errors(),
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

from app.api.auth import get_current_admin

app.include_router(auth_router)
app.include_router(backup_router, dependencies=[Depends(get_current_admin)])
app.include_router(network_router, dependencies=[Depends(get_current_admin)])
app.include_router(topology_router, dependencies=[Depends(get_current_admin)])
app.include_router(devices_router, dependencies=[Depends(get_current_admin)])
app.include_router(groups_router, dependencies=[Depends(get_current_admin)])
app.include_router(router_services, dependencies=[Depends(get_current_admin)])
app.include_router(scanner_router, dependencies=[Depends(get_current_admin)])
app.include_router(settings_router, dependencies=[Depends(get_current_admin)])
app.include_router(setup_router) # Setup manages its own logic
app.include_router(agent_router) # Contains both public report and protected metrics (internally handled)
logger.info("Registered Agent API routes under /api/agent")


@app.get("/api/health")
async def health_check() -> dict:
    """Health check endpoint for Docker and monitoring."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "app": settings.app_name,
    }


@app.websocket("/api/logs/ws")
async def logs_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time backend log streaming with authentication."""
    from app.api.auth import authenticate_websocket
    auth_info = await authenticate_websocket(websocket, endpoint_type="logs")
    if not auth_info.get("authenticated"):
        return

    # Logs are strictly restricted to browser-sessions, master tokens, or legacy master tokens
    if auth_info.get("auth_type") not in ("session", "master", "master_legacy"):
        await websocket.close(code=4003, reason="Unauthorized access level")
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


# --- Serve React Frontend (production) ---
@app.get("/")
async def root():
    """Root endpoint: Serve frontend if available, else status JSON."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {
        "app": "GravityLAN",
        "version": VERSION,
        "status": "online",
        "api_docs": "/docs",
        "message": "Backend is running. Frontend build missing in /app/static."
    }

if FRONTEND_DIR.exists():
    # Only mount if the directories actually exist to prevent startup crashes
    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists() and assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Exclude API calls from the catch-all
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        
        # Exclude existing files (assets/etc)
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
            
        # Fallback to index.html for SPA routing
        index_file = FRONTEND_DIR / "index.html"
        return FileResponse(index_file)

    logger.info("Serving SPA frontend from: %s", FRONTEND_DIR)


async def prune_metrics_loop():
    """Background task to prune old metrics periodically."""
    from app.models.agent import DeviceMetrics
    from app.database import async_session
    from sqlalchemy import delete
    
    while True:
        try:
            # Wait 1 hour between runs
            await asyncio.sleep(3600)
            
            async with async_session() as db:
                logger.info("Starting background metrics pruning...")
                # Keep last 24h of metrics
                cutoff = datetime.now() - timedelta(hours=24)
                result = await db.execute(
                    delete(DeviceMetrics).where(DeviceMetrics.timestamp < cutoff)
                )
                await db.commit()
                logger.info("Pruned %d old metric entries.", result.rowcount)
        except asyncio.CancelledError:
            logger.info("Background metrics pruning task cancelled.")
            raise
        except Exception as e:
            logger.error("Background pruning failed: %s", e)
            await asyncio.sleep(60) # Wait a bit before retry if failed
