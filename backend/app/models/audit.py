"""Audit log: who did what, when, from where, to which device, and how it ended."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuditEvent(Base):
    """One administrative action. Never holds secrets or terminal input.

    ``device_id`` has no foreign key on purpose: the entry outlives the device it names.
    The table is not part of backups and survives a database reset.
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    # "session", "master", "api_token:<name>", "anonymous" (failed login), "setup"
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    source_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # Dotted name, e.g. "agent.deploy", "ssh.terminal.open", "auth.login"
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    # "ok", "failed" or "denied"
    result: Mapped[str] = mapped_column(String(12), nullable=False, default="ok")
    device_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    target: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    detail: Mapped[str] = mapped_column(String(500), nullable=False, default="")
