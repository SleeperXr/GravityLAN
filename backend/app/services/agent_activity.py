"""When an agent counts as active: relative to its own reporting interval (5 to 300 seconds)."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig
from app.scanner.utils import ensure_utc

DEFAULT_INTERVAL = 30


def active_window(interval: int | None) -> int:
    """Seconds without a report before an agent is inactive: three missed reports, at least two minutes."""
    return max(120, 3 * (interval or DEFAULT_INTERVAL))


def stale_window(interval: int | None) -> int:
    """Seconds without a report before a failed probe alone may call the host offline."""
    return max(75, int(2.5 * (interval or DEFAULT_INTERVAL)))


def has_active_token(token: Any) -> bool:
    """True only when ``token`` exists and explicitly marks ``is_active`` as active.

    Conservative rule: ``None``, missing ``is_active``, ``is_active=None``, ``False`` or ``0``
    are never treated as active. Only explicit ``True`` (or SQLite integer ``1``) qualifies.
    """
    if token is None:
        return False
    is_active = getattr(token, "is_active", False)
    return is_active is True or (type(is_active) is int and is_active == 1)


def is_token_reporting(token: Any, interval: int | None, now: datetime) -> bool:
    """True when ``token`` is active and reported within ``active_window(interval)``."""
    if not has_active_token(token):
        return False
    last_seen = ensure_utc(token.last_seen)
    return bool(last_seen and (now - last_seen).total_seconds() < active_window(interval))


async def load_intervals(db: AsyncSession) -> dict[int, int]:
    """Reporting interval per device; a device without a config reports at the default."""
    rows = await db.execute(select(AgentConfig.device_id, AgentConfig.interval))
    return dict(rows.all())
