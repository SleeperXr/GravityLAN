import hmac
from pydantic import RootModel
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, text
from app.database import get_db
from app.models.device import Device, Service, DeviceGroup
from app.models.setting import Setting
import logging

logger = logging.getLogger(__name__)
from app.api.auth import get_current_admin

router = APIRouter(prefix="/api/settings", tags=["settings"])

@router.get("", dependencies=[Depends(get_current_admin)])
async def get_all_settings(db: AsyncSession = Depends(get_db)):
    """Fetch all system settings as a key-value dictionary."""
    result = await db.execute(select(Setting))
    settings = result.scalars().all()
    return {s.key: s.value for s in settings}

SettingsUpdate = RootModel[dict[str, str]]

@router.post("", dependencies=[Depends(get_current_admin)])
async def update_settings(settings: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    """Update or create system settings."""
    for key, value in settings.root.items():
        # Validate scan_subnets if provided
        if key == "scan_subnets" and value:
            import ipaddress
            invalid_subnets = []
            for sub in value.split(","):
                sub = sub.strip()
                if not sub: continue
                try:
                    ipaddress.ip_network(sub, strict=False)
                except ValueError:
                    invalid_subnets.append(sub)
            
            if invalid_subnets:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Ungültige Subnetze: {', '.join(invalid_subnets)}. Bitte im Format 192.168.1.0/24 angeben."
                )

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
            tables = [
                "topology_links", "device_metrics", "agent_tokens", "agent_configs",
                "device_history", "services", "devices", "racks", "discovered_hosts",
                "subnets", "app_settings"
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
