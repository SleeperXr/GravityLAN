"""Settings > Measurement data: telemetry database size, retention and purging.

Mounted under /api/settings/telemetry, so the existing scope mapping applies:
reading needs ``settings:read``, changing or deleting ``settings:write``; every
route sits behind get_current_admin.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_admin
from app.database import get_db
from app.models.device import Device
from app.services.telemetry_store import (
    DAILY_RETENTION,
    HOURLY_RETENTION,
    RAW_RETENTION,
    TelemetryRetention,
    database_sizes,
    get_retention,
    purge_telemetry,
    reclaim_telemetry_space,
    retention_as_dict,
    save_retention,
    table_stats,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings/telemetry", tags=["telemetry"], dependencies=[Depends(get_current_admin)])


class TelemetryRetentionUpdate(BaseModel):
    raw_hours: int = Field(ge=RAW_RETENTION.minimum, le=RAW_RETENTION.maximum)
    hourly_days: int = Field(ge=HOURLY_RETENTION.minimum, le=HOURLY_RETENTION.maximum)
    daily_days: int = Field(ge=DAILY_RETENTION.minimum, le=DAILY_RETENTION.maximum)

    @model_validator(mode="after")
    def _tiers_nest(self):
        # A coarser tier has to reach back at least as far as the finer one, or the
        # rollups would be pruned before anything older than the finer tier exists
        if self.hourly_days * 24 < self.raw_hours:
            raise ValueError("hourly_days must cover at least raw_hours")
        if self.daily_days < self.hourly_days:
            raise ValueError("daily_days must be at least hourly_days")
        return self


class TelemetryPurgeRequest(BaseModel):
    scope: Literal["older_than", "device", "all"]
    older_than_days: int | None = Field(default=None, ge=1, le=3650)
    device_id: int | None = None

    @model_validator(mode="after")
    def _scope_args(self):
        if self.scope == "older_than" and self.older_than_days is None:
            raise ValueError("older_than_days is required for scope 'older_than'")
        if self.scope == "device" and self.device_id is None:
            raise ValueError("device_id is required for scope 'device'")
        return self


async def _status(db: AsyncSession) -> dict:
    retention = await get_retention(db)
    return {
        "sizes": await database_sizes(db),
        "tables": await table_stats(db),
        "retention": retention_as_dict(retention),
        "limits": {
            name: {"min": limits.minimum, "max": limits.maximum, "default": limits.default}
            for name, limits in (
                ("raw_hours", RAW_RETENTION), ("hourly_days", HOURLY_RETENTION), ("daily_days", DAILY_RETENTION)
            )
        },
    }


@router.get("")
async def get_telemetry_status(db: AsyncSession = Depends(get_db)) -> dict:
    """Sizes of both databases, rows per measurement table and the retention per tier."""
    return await _status(db)


@router.put("/retention")
async def update_telemetry_retention(update: TelemetryRetentionUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    """Store the retention per tier; the next hourly maintenance run applies it."""
    await save_retention(db, TelemetryRetention(**update.model_dump()))
    logger.info("Telemetry retention changed: %s", update.model_dump())
    return await _status(db)


@router.post("/purge")
async def purge_telemetry_data(request: TelemetryPurgeRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Delete measurement data (older than N days, of one device, or all) and free the space."""
    older_than = None
    device_id = None
    if request.scope == "older_than":
        older_than = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=request.older_than_days)
    elif request.scope == "device":
        if await db.get(Device, request.device_id) is None:
            raise HTTPException(status_code=404, detail="Device not found")
        device_id = request.device_id

    deleted = await purge_telemetry(db, older_than=older_than, device_id=device_id)
    await reclaim_telemetry_space(db)
    logger.warning("Telemetry purged (%s): %s", request.scope, deleted)
    return {"deleted": deleted, **await _status(db)}
