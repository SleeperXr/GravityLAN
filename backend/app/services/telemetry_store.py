"""Telemetry database housekeeping: retention settings, sizes, purging, legacy move.

The measurement tables (raw health samples and agent metrics plus their hourly and
daily rollups) live in ``telemetry.db``, attached as schema ``telemetry`` (see
app.database). This module owns everything that treats that file as a whole:

* the per-tier retention settings,
* deleting a device's telemetry (there is no foreign key across the two files),
* the purge actions of Settings > Measurement data, followed by giving the space back,
* moving the tables an older version kept in the inventory file into telemetry.db.
"""

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import settings
from app.database import TELEMETRY_SCHEMA
from app.models.agent import DeviceMetrics
from app.models.device import DeviceHealthSample
from app.models.setting import Setting
from app.models.telemetry import DeviceHealthRollup, DeviceMetricsRollup

logger = logging.getLogger(__name__)

# Raw and rolled-up measurement models with the column their age is measured by
TELEMETRY_MODELS = (
    (DeviceHealthSample, DeviceHealthSample.timestamp),
    (DeviceMetrics, DeviceMetrics.timestamp),
    (DeviceHealthRollup, DeviceHealthRollup.bucket_start),
    (DeviceMetricsRollup, DeviceMetricsRollup.bucket_start),
)

# Tables an older version kept in the inventory file (moved by migrate_legacy_telemetry)
LEGACY_TABLES = ("device_health_samples", "device_metrics")


@dataclass(frozen=True)
class RetentionLimits:
    """Allowed range and default of one retention setting."""

    key: str
    default: int
    minimum: int
    maximum: int


RAW_RETENTION = RetentionLimits("telemetry.raw_retention_hours", 48, 24, 720)
HOURLY_RETENTION = RetentionLimits("telemetry.hourly_retention_days", 30, 2, 365)
DAILY_RETENTION = RetentionLimits("telemetry.daily_retention_days", 365, 7, 3650)


@dataclass(frozen=True)
class TelemetryRetention:
    """How long each tier is kept: raw rows in hours, rollups in days."""

    raw_hours: int = RAW_RETENTION.default
    hourly_days: int = HOURLY_RETENTION.default
    daily_days: int = DAILY_RETENTION.default

    @property
    def history_days(self) -> int:
        """Longest time span any tier still covers (bounds the selectable chart ranges)."""
        return max(self.raw_hours // 24, self.hourly_days, self.daily_days)


def _clamp_setting(raw: str | None, limits: RetentionLimits) -> int:
    try:
        value = int(raw) if raw is not None else limits.default
    except (TypeError, ValueError):
        return limits.default
    return min(limits.maximum, max(limits.minimum, value))


async def get_retention(db: AsyncSession) -> TelemetryRetention:
    """Read the retention settings; missing or invalid values fall back to the defaults."""
    keys = (RAW_RETENTION.key, HOURLY_RETENTION.key, DAILY_RETENTION.key)
    res = await db.execute(select(Setting.key, Setting.value).where(Setting.key.in_(keys)))
    values = dict(res.all())
    return TelemetryRetention(
        raw_hours=_clamp_setting(values.get(RAW_RETENTION.key), RAW_RETENTION),
        hourly_days=_clamp_setting(values.get(HOURLY_RETENTION.key), HOURLY_RETENTION),
        daily_days=_clamp_setting(values.get(DAILY_RETENTION.key), DAILY_RETENTION),
    )


async def save_retention(db: AsyncSession, retention: TelemetryRetention) -> None:
    """Persist the retention settings (the caller validated the ranges)."""
    for limits, value in (
        (RAW_RETENTION, retention.raw_hours),
        (HOURLY_RETENTION, retention.hourly_days),
        (DAILY_RETENTION, retention.daily_days),
    ):
        setting = (await db.execute(select(Setting).where(Setting.key == limits.key))).scalar_one_or_none()
        if setting:
            setting.value = str(value)
        else:
            db.add(Setting(key=limits.key, value=str(value)))
    await db.commit()


def retention_as_dict(retention: TelemetryRetention) -> dict:
    return asdict(retention)


async def delete_device_telemetry(db: AsyncSession, device_ids: list[int]) -> int:
    """Delete every measurement row of the given devices (caller commits).

    Needed wherever a device disappears from the inventory: the telemetry file has
    no foreign key to it that could cascade.
    """
    if not device_ids:
        return 0
    deleted = 0
    for model, _age_column in TELEMETRY_MODELS:
        res = await db.execute(delete(model).where(model.device_id.in_(device_ids)))
        deleted += res.rowcount or 0
    return deleted


async def purge_telemetry(
    db: AsyncSession,
    *,
    older_than: datetime | None = None,
    device_id: int | None = None,
) -> dict[str, int]:
    """Delete measurement rows of every tier and commit; returns deleted rows per table.

    ``older_than`` (naive UTC) limits it to older rows, ``device_id`` to one device;
    without either, everything goes.
    """
    counts: dict[str, int] = {}
    for model, age_column in TELEMETRY_MODELS:
        stmt = delete(model)
        if older_than is not None:
            stmt = stmt.where(age_column < older_than)
        if device_id is not None:
            stmt = stmt.where(model.device_id == device_id)
        res = await db.execute(stmt)
        counts[model.__tablename__] = res.rowcount or 0
    await db.commit()
    return counts


def _is_sqlite(db: AsyncSession) -> bool:
    return db.get_bind().dialect.name == "sqlite"


async def reclaim_telemetry_space(db: AsyncSession) -> None:
    """Hand pages freed by deletes back to the file system.

    telemetry.db is created with auto_vacuum=INCREMENTAL, so this needs no full
    VACUUM. The pragma frees one page per step and Python's execute() steps only
    once, so it runs through executescript(), which steps it to completion.
    """
    if not _is_sqlite(db):
        return
    await db.commit()
    conn = await db.connection()
    raw = await conn.get_raw_connection()
    await raw.driver_connection.executescript(f"PRAGMA {TELEMETRY_SCHEMA}.incremental_vacuum;")
    await db.commit()
    # The WAL keeps the deleted pages until a checkpoint; truncate it as well
    (await db.execute(text(f"PRAGMA {TELEMETRY_SCHEMA}.wal_checkpoint(TRUNCATE)"))).fetchall()
    await db.commit()


async def _schema_bytes(db: AsyncSession, schema: str) -> tuple[int, int]:
    """(allocated bytes, free bytes) of one attached SQLite schema."""
    page_size = (await db.execute(text(f"PRAGMA {schema}.page_size"))).scalar() or 0
    page_count = (await db.execute(text(f"PRAGMA {schema}.page_count"))).scalar() or 0
    free_pages = (await db.execute(text(f"PRAGMA {schema}.freelist_count"))).scalar() or 0
    return page_size * page_count, page_size * free_pages


def _wal_bytes(path: str) -> int:
    if not path or path == ":memory:":
        return 0
    try:
        return os.path.getsize(f"{path}-wal")
    except OSError:
        return 0


def _main_database_path() -> str:
    url = settings.effective_database_url
    return url.split(":///", 1)[1] if "sqlite" in url and ":///" in url else ""


async def database_sizes(db: AsyncSession) -> dict[str, int]:
    """Size in bytes of the inventory and the telemetry database (including WAL files)."""
    if not _is_sqlite(db):
        return {"inventory_bytes": 0, "telemetry_bytes": 0, "telemetry_free_bytes": 0}
    inventory, _ = await _schema_bytes(db, "main")
    telemetry, telemetry_free = await _schema_bytes(db, TELEMETRY_SCHEMA)
    return {
        "inventory_bytes": inventory + _wal_bytes(_main_database_path()),
        "telemetry_bytes": telemetry + _wal_bytes(settings.telemetry_database_path),
        "telemetry_free_bytes": telemetry_free,
    }


async def table_stats(db: AsyncSession) -> dict[str, dict]:
    """Row count and oldest/newest entry per measurement table."""
    stats: dict[str, dict] = {}
    for model, age_column in TELEMETRY_MODELS:
        row = (await db.execute(
            select(func.count(), func.min(age_column), func.max(age_column)).select_from(model)
        )).one()
        stats[model.__tablename__] = {"rows": row[0] or 0, "oldest": row[1], "newest": row[2]}
    return stats


async def _legacy_columns(db: AsyncSession, table: str) -> list[str]:
    """Columns the inventory copy of ``table`` shares with its telemetry table (empty if none)."""
    exists = (await db.execute(
        text("SELECT 1 FROM main.sqlite_master WHERE type = 'table' AND name = :t"), {"t": table}
    )).first()
    if not exists:
        return []
    legacy = {r[1] for r in (await db.execute(text(f"PRAGMA main.table_info({table})"))).all()}
    current = [r[1] for r in (await db.execute(text(f"PRAGMA {TELEMETRY_SCHEMA}.table_info({table})"))).all()]
    return [c for c in current if c in legacy]


async def migrate_legacy_telemetry(db: AsyncSession) -> int:
    """Move measurement tables that still sit in the inventory file into telemetry.db.

    Runs at startup after init_db and the column migrations. Repeatable: rows are
    copied with their ids and ``INSERT OR IGNORE``, so an interrupted run that
    copied without dropping just copies nothing new the next time. Returns the
    number of rows moved (then the caller should VACUUM the inventory file).
    """
    if not _is_sqlite(db):
        return 0
    moved = 0
    for table in LEGACY_TABLES:
        columns = await _legacy_columns(db, table)
        if not columns:
            continue
        cols = ", ".join(columns)
        res = await db.execute(text(
            f"INSERT OR IGNORE INTO {TELEMETRY_SCHEMA}.{table} ({cols}) SELECT {cols} FROM main.{table}"
        ))
        await db.execute(text(f"DROP TABLE main.{table}"))
        await db.commit()
        copied = res.rowcount or 0
        moved += copied
        logger.info("Telemetry: moved %d rows of %s from the inventory into telemetry.db", copied, table)
    return moved


async def vacuum_inventory(engine: AsyncEngine) -> None:
    """Shrink the inventory file after the telemetry tables left it.

    Switches it to auto_vacuum=INCREMENTAL on the way (that needs a full VACUUM
    once), so later deletes in the inventory give their space back as well.
    """
    if engine.dialect.name != "sqlite":
        return
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("PRAGMA main.auto_vacuum=INCREMENTAL")
        await conn.exec_driver_sql("VACUUM main")
    logger.info("Telemetry: inventory database vacuumed after the move")
