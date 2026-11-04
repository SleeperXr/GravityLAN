"""When an agent counts as active: relative to its own reporting interval (5 to 300 seconds)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig

DEFAULT_INTERVAL = 30


def active_window(interval: int | None) -> int:
    """Seconds without a report before an agent is inactive: three missed reports, at least two minutes."""
    return max(120, 3 * (interval or DEFAULT_INTERVAL))


def stale_window(interval: int | None) -> int:
    """Seconds without a report before a failed probe alone may call the host offline."""
    return max(75, int(2.5 * (interval or DEFAULT_INTERVAL)))


async def load_intervals(db: AsyncSession) -> dict[int, int]:
    """Reporting interval per device; a device without a config reports at the default."""
    rows = await db.execute(select(AgentConfig.device_id, AgentConfig.interval))
    return dict(rows.all())
