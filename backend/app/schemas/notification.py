"""Pydantic schemas for system notifications."""

from datetime import datetime
from pydantic import BaseModel

class NotificationResponse(BaseModel):
    """System notification message representation."""
    id: int
    title: str
    message: str
    type: str  # "success", "warning", "error", "info"
    timestamp: datetime
    read: bool = False
