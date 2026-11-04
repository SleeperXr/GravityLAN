"""SQLAlchemy models for Webhook Subscriptions and Notification Outbox."""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class WebhookSubscription(Base):
    """Webhook Subscriptions for event notification dispatch."""
    __tablename__ = "webhook_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    service_type: Mapped[str] = mapped_column(String(20), default="webhook", server_default="webhook", nullable=False)  # "webhook", "ntfy", "gotify"
    encrypted_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    events: Mapped[str] = mapped_column(String(500), nullable=False)  # e.g. "device.offline,scan.complete"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def has_token(self) -> bool:
        return bool(self.encrypted_token)


class NotificationOutbox(Base):
    """Persistent notification outbox with delivery attempts."""
    __tablename__ = "notification_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("webhook_subscriptions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    service_type: Mapped[str] = mapped_column(String(20), default="webhook", server_default="webhook", nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False, index=True
    )  # "pending", "delivered", "failed"
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
