"""Notifications aggregate API router for GravityLAN."""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
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
    db: AsyncSession = Depends(get_db),
    current_admin: str = Depends(get_current_admin)
) -> list[NotificationResponse]:
    """Retrieve dynamic notifications aggregated from system history logs with filtering support."""
    # Since all notifications are currently unread (read=False), if unread filter is explicitly False, return empty.
    if unread is False:
        return []

    query = select(DeviceHistory).options(
        selectinload(DeviceHistory.device),
        selectinload(DeviceHistory.service)
    )
    
    if device_id is not None:
        query = query.where(DeviceHistory.device_id == device_id)
        
    if since is not None:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        query = query.where(DeviceHistory.timestamp >= since)
        
    query = query.order_by(DeviceHistory.timestamp.desc()).limit(50)
    
    result = await db.execute(query)
    history_entries = result.scalars().all()
    
    notifications = []
    for h in history_entries:
        # Determine event properties
        if h.service_id:
            # Service event
            if h.status in ("up", "online"):
                title = "🟢 Service online"
                severity = "success"
                event_type = "service_up"
            else:
                title = "⚠️ Service ausgefallen"
                severity = "error"
                event_type = "service_down"
        else:
            # Device event
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
                read=False,
                timestamp=h.timestamp,
                type=event_type,
                severity=severity,
                device_id=h.device_id
            )
        )
        
    return notifications

