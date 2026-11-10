"""Notifications aggregate API router for GravityLAN."""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.api.auth import get_current_admin
from app.models.device import DeviceHistory
from app.schemas.notification import NotificationResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    since: datetime | None = None,
    unread: bool | None = None,
    device_id: int | None = None,
    # A negative limit used to lift the cap (SQLite reads LIMIT -1 as "no limit")
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_admin: str = Depends(get_current_admin)
) -> list[NotificationResponse]:
    """Retrieve dynamic notifications aggregated from system history logs with filtering support."""
    query = select(DeviceHistory).options(
        selectinload(DeviceHistory.device),
        selectinload(DeviceHistory.service)
    )

    if unread is True:
        query = query.where(DeviceHistory.read == False)
    elif unread is False:
        query = query.where(DeviceHistory.read == True)

    if device_id is not None:
        query = query.where(DeviceHistory.device_id == device_id)

    if since is not None:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        query = query.where(DeviceHistory.timestamp >= since)

    query = query.order_by(DeviceHistory.timestamp.desc()).limit(limit)

    result = await db.execute(query)
    history_entries = result.scalars().all()

    notifications = []
    for h in history_entries:
        if h.service_id:
            if h.status in ("up", "online"):
                title = "🟢 Service online"
                severity = "success"
                event_type = "service_up"
            else:
                title = "⚠️ Service ausgefallen"
                severity = "error"
                event_type = "service_down"
        else:
            if h.status in ("online", "up"):
                title = "🟢 Gerät online"
                severity = "success"
                event_type = "device_online"
            elif h.status in ("offline", "down"):
                title = "🔴 Gerät offline"
                severity = "warning"
                event_type = "device_offline"
            elif h.status == "ip_changed":
                title = "📡 IP-Adresse geändert"
                severity = "info"
                event_type = "ip_changed"
            elif h.status == "new_device":
                title = "✨ Neues Gerät"
                severity = "info"
                event_type = "new_device"
            else:
                title = "System-Ereignis"
                severity = "info"
                event_type = "unknown"

        dev_name = h.device.display_name or h.device.ip if h.device else f"Device #{h.device_id}"
        msg = h.message or f"{dev_name} is now {h.status}"

        notifications.append(
            NotificationResponse(
                id=h.id,
                title=title,
                message=msg,
                read=bool(getattr(h, "read", False)),
                timestamp=h.timestamp,
                type=event_type,
                severity=severity,
                device_id=h.device_id
            )
        )

    return notifications


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: str = Depends(get_current_admin)
) -> dict:
    """Mark a single notification as read."""
    entry = await db.get(DeviceHistory, notification_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Notification not found")
    entry.read = True
    await db.commit()
    return {"status": "success", "id": notification_id, "read": True}


@router.post("/read-all")
async def mark_all_notifications_read(
    device_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_admin: str = Depends(get_current_admin)
) -> dict:
    """Mark all unread notifications as read, optionally filtered by device."""
    stmt = update(DeviceHistory).where(DeviceHistory.read == False)
    if device_id is not None:
        stmt = stmt.where(DeviceHistory.device_id == device_id)
    stmt = stmt.values(read=True)
    res = await db.execute(stmt)
    await db.commit()
    return {"status": "success", "marked_read": res.rowcount or 0}
