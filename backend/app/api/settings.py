from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete
from app.database import get_db
from app.models.device import Device, Service, DeviceGroup
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])

from sqlalchemy import select
from app.models.setting import Setting

@router.get("")
async def get_all_settings(db: AsyncSession = Depends(get_db)):
    """Fetch all system settings as a key-value dictionary."""
    result = await db.execute(select(Setting))
    settings = result.scalars().all()
    return {s.key: s.value for s in settings}

@router.post("")
async def update_settings(settings: dict[str, str], db: AsyncSession = Depends(get_db)):
    """Update or create system settings."""
    for key, value in settings.items():
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.value = value
        else:
            db.add(Setting(key=key, value=value))
    
    await db.commit()
    
    # Apply log level if changed
    if "system.log_level" in settings:
        from app.services.log_streamer import apply_log_level
        apply_log_level(settings["system.log_level"])
        
    return {"status": "success"}


@router.post("/reset-db", status_code=200)
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

        from app.models.device import DeviceHistory, DiscoveredHost
        from app.models.agent import AgentToken, DeviceMetrics, AgentConfig
        await db.execute(delete(DeviceMetrics))
        await db.execute(delete(AgentToken))
        await db.execute(delete(AgentConfig))
        await db.execute(delete(Service))
        await db.execute(delete(DeviceHistory))
        await db.execute(delete(Device))
        await db.execute(delete(DiscoveredHost))
        await db.execute(delete(DeviceGroup).where(DeviceGroup.is_default == False))
        
        # Reset setup status
        await db.execute(delete(Setting).where(Setting.key == "setup.complete"))
        
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
