"""Edge cases of the telemetry store (app/services/telemetry_store.py): bad retention values, updating
stored settings, other database engines, WAL file sizes and vacuuming the inventory file."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.setting import Setting
from app.services import telemetry_store as ts


@pytest.mark.parametrize(
    "raw, expected",
    [(None, 48), ("abc", 48), ("100", 100), ("1", 24), ("99999", 720)],
)
def test_clamp_setting(raw, expected):
    assert ts._clamp_setting(raw, ts.RAW_RETENTION) == expected


@pytest.mark.asyncio
async def test_saving_retention_twice_updates_the_stored_values(db):
    await ts.save_retention(db, ts.TelemetryRetention(raw_hours=72, hourly_days=10, daily_days=100))
    await ts.save_retention(db, ts.TelemetryRetention(raw_hours=96, hourly_days=20, daily_days=200))

    rows = (await db.execute(select(Setting.key, Setting.value).where(Setting.key.like("telemetry.%")))).all()
    expected = [(ts.RAW_RETENTION.key, "96"), (ts.HOURLY_RETENTION.key, "20"), (ts.DAILY_RETENTION.key, "200")]
    assert sorted(rows) == sorted(expected)
    retention = await ts.get_retention(db)
    assert (retention.raw_hours, retention.history_days) == (96, 200)


@pytest.mark.asyncio
async def test_deleting_telemetry_of_no_devices_does_nothing(db):
    assert await ts.delete_device_telemetry(db, []) == 0


@pytest.mark.asyncio
async def test_sqlite_only_steps_are_skipped_on_other_engines():
    other = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    assert await ts.reclaim_telemetry_space(other) is None
    assert await ts.database_sizes(other) == {"inventory_bytes": 0, "telemetry_bytes": 0, "telemetry_free_bytes": 0}
    assert await ts.migrate_legacy_telemetry(other) == 0
    assert await ts.vacuum_inventory(SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))) is None


def test_wal_bytes(tmp_path):
    db_file = tmp_path / "inventory.db"
    assert ts._wal_bytes("") == 0
    assert ts._wal_bytes(":memory:") == 0
    assert ts._wal_bytes(str(db_file)) == 0  # no WAL file
    (tmp_path / "inventory.db-wal").write_bytes(b"x" * 123)
    assert ts._wal_bytes(str(db_file)) == 123


@pytest.mark.asyncio
async def test_vacuum_inventory_switches_to_incremental_auto_vacuum(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'inventory.db').as_posix()}")
    try:
        await ts.vacuum_inventory(engine)
        async with engine.connect() as conn:
            assert (await conn.exec_driver_sql("PRAGMA main.auto_vacuum")).scalar() == 2  # INCREMENTAL
    finally:
        await engine.dispose()
