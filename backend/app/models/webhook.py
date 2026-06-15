"""SQLAlchemy model for Webhook Subscriptions."""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class WebhookSubscription(Base):
    """Webhook Subscriptions for event notification dispatch."""
    __tablename__ = "webhook_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    events: Mapped[str] = mapped_column(String(500), nullable=False) # e.g. "device.offline,scan.complete"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
