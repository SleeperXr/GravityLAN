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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi import WebSocket, WebSocketDisconnect

from app.config import settings
from app.database import init_db

logger = logging.getLogger(__name__)

# Detection: Use /app/static in Docker, fallback to local dist for development
FRONTEND_DIR = Path("/app/static") if Path("/app/static").exists() else Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager — runs on startup and shutdown."""
    # Startup
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Aggressively suppress aiosqlite logs (usually not needed even with SQL logs)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    # Custom filter for Uvicorn access logs to ignore polling noise
    class PollingFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            # Ignore frequent polling endpoints and binary health checks
            if any(x in msg for x in ["/api/agent/status/", "/api/devices", "/api/groups", "/api/scanner/status", "/api/health", "/api/scanner/ws"]):
                return False
            return True

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

    # Ensure data directory exists
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    # Initialize database tables
    await init_db()
    logger.info("Database initialized: %s", settings.effective_database_url)

    # Start the scan scheduler
    from app.scanner.scheduler import scheduler
    await scheduler.start()

    # Migration: Fix missing/wrong service colors for existing entries
    from app.database import async_session
    from app.models.device import Service
    from app.scanner.classifier import SERVICE_TEMPLATES
    from sqlalchemy import select

    async with async_session() as db:
        res = await db.execute(select(Service).where(Service.is_auto_detected == True))
        services = res.scalars().all()
        fixed_count = 0
        for svc in services:
            # If color is missing or generic blue, try to find a better one
            if not svc.color or svc.color == "#34495e":
                for template in SERVICE_TEMPLATES.values():
                    if template.get("port") == svc.port:
                        svc.color = template["color"]
                        fixed_count += 1
                        break
        if fixed_count > 0:
            await db.commit()
            logger.info("Auto-fixed colors for %d existing services", fixed_count)

    # Auto-Migration: Ensure all new columns exist in both tables
    from sqlalchemy import text
    async with async_session() as db:
        for table in ["devices", "discovered_hosts"]:
            # Standard columns
            for column, col_type in [("is_reserved", "BOOLEAN DEFAULT 0"), ("old_ip", "VARCHAR(45)"), ("ip_changed_at", "DATETIME")]:
                try:
                    await db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                    await db.commit()
                    logger.info("Database Migration: Added '%s' column to '%s'", column, table)
                except Exception:
                    await db.rollback()
            
            # Table specific columns
            if table == "discovered_hosts":
                for column, col_type in [("ports", "TEXT")]:
                    try:
                        await db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                        await db.commit()
                        logger.info("Database Migration: Added '%s' column to '%s'", column, table)
                    except Exception:
                        await db.rollback()

        # Migration for agent_configs
        for column, col_type in [("version", "INTEGER DEFAULT 1")]:
            try:
                await db.execute(text(f"ALTER TABLE agent_configs ADD COLUMN {column} {col_type}"))
                await db.commit()
                logger.info("Database Migration: Added '%s' column to 'agent_configs'", column)
            except Exception:
                await db.rollback()

        # Migration for devices specifically
        for column, col_type in [("has_agent", "BOOLEAN DEFAULT 0")]:
            try:
                await db.execute(text(f"ALTER TABLE devices ADD COLUMN {column} {col_type}"))
                await db.commit()
                logger.info("Database Migration: Added '%s' column to 'devices'", column)
            except Exception:
                await db.rollback()

    yield

    # Shutdown
    from app.scanner.scheduler import scheduler
    await scheduler.stop()
    logger.info("GravityLAN shutting down.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# Exception Handler for Validation Errors (to log 422 errors)
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error("Validation error on %s: %s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": str(exc.body) if hasattr(exc, "body") else None},
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
from app.api.devices import groups_router, router_services, router as devices_router  # noqa: E402
from app.api.scanner import router as scanner_router  # noqa: E402
from app.api.settings import router as settings_router  # noqa: E402
from app.api.setup import router as setup_router  # noqa: E402
from app.api.agent import router as agent_router  # noqa: E402
from app.api.backup import router as backup_router  # noqa: E402

app.include_router(backup_router)
app.include_router(devices_router)
app.include_router(groups_router)
app.include_router(router_services)
app.include_router(scanner_router)
app.include_router(settings_router)
app.include_router(setup_router)
app.include_router(agent_router)
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
    """WebSocket endpoint for real-time backend log streaming."""
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
        "version": "0.1.0",
        "status": "online",
        "api_docs": "/docs",
        "message": "Backend is running. Frontend build missing in /app/static."
    }

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")
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
