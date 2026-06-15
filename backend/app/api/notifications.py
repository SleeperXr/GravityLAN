"""Notifications aggregate API router for GravityLAN."""

import logging
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
    db: AsyncSession = Depends(get_db),
    current_admin: str = Depends(get_current_admin)
) -> list[NotificationResponse]:
    """Retrieve dynamic notifications aggregated from system history logs."""
    # Query last 50 history entries, eager loading relations
    result = await db.execute(
        select(DeviceHistory)
        .options(selectinload(DeviceHistory.device), selectinload(DeviceHistory.service))
        .order_by(DeviceHistory.timestamp.desc())
        .limit(50)
    )
    history_entries = result.scalars().all()
    
    notifications = []
    for h in history_entries:
        # Determine notification properties based on event type and status
        if h.service_id:
            # Service event
            if h.status in ("up", "online"):
                title = "🟢 Service online"
                ntype = "success"
            else:
                title = "⚠️ Service ausgefallen"
                ntype = "error"
        else:
            # Device event
            if h.status in ("online", "up"):
                title = "🟢 Gerät online"
                ntype = "success"
            elif h.status in ("offline", "down"):
                title = "🔴 Gerät offline"
                ntype = "warning"
            elif h.status == "ip_changed":
                title = "📡 IP-Adresse geändert"
                ntype = "info"
            else:
                title = "System-Ereignis"
                ntype = "info"
        
        dev_name = h.device.display_name or h.device.ip if h.device else f"Device #{h.device_id}"
        msg = h.message or f"{dev_name} is now {h.status}"
        
        notifications.append(
            NotificationResponse(
                id=h.id,
                title=title,
                message=msg,
                type=ntype,
                timestamp=h.timestamp,
                read=False
            )
        )
        
    return notifications
