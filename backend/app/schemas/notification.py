"""Pydantic schemas for system notifications."""

from datetime import datetime
from pydantic import BaseModel

class NotificationResponse(BaseModel):
    """System notification message representation."""
    id: int
    title: str
    message: str
    read: bool = False
    timestamp: datetime
    type: str = "unknown"  # "device_offline", "device_online", "service_down", "service_up", "ip_changed", "unknown"
    severity: str = "info"  # "success", "warning", "error", "info"
    device_id: int | None = None
