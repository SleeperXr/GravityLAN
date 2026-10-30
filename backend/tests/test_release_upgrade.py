"""Release gates: an older release's database upgrades cleanly, and a backup survives export and import.

The databases under fixtures/db are frozen per release by scripts/freeze_release_db.py (docs/RELEASING.md).
"""

import logging
import re
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import backup
from app.config import settings as app_config
from app.database import Base, attach_telemetry_database
from app.database.migrations import run_migrations

FROZEN_DIR = Path(__file__).parent / "fixtures" / "db"
PROTECTED = set(backup.PROTECTED_SETTING_KEYS)


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", path.stem))


FROZEN = sorted(FROZEN_DIR.glob("gravitylan-*.sql"), key=_version_key)
INVENTORY_TABLES = [t for t in Base.metadata.sorted_tables if t.schema is None]


def _restore(sql_file: Path, db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(sql_file.read_text(encoding="utf-8"))
    finally:
        conn.close()


def _columns(db_path: Path) -> dict[str, set[str]]:
    conn = sqlite3.connect(db_path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: {r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')} for t in tables}
    finally:
        conn.close()


def _row_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


async def _start_like_main(db_path: Path, telemetry_path: Path) -> None:
    """What main.py's lifespan does to the database on start: create_all, then run_migrations."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    @event.listens_for(engine.sync_engine, "connect")
    def _attach(dbapi_connection, _record):
        attach_telemetry_database(dbapi_connection, str(telemetry_path))

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as db:
            await run_migrations(db)
    finally:
        await engine.dispose()


@pytest.fixture
def docker_unavailable(monkeypatch):
    docker_service = MagicMock()
    docker_service.is_available.return_value = False
    monkeypatch.setattr("app.services.docker_service.docker_service", docker_service)


def test_a_release_database_is_frozen():
    assert FROZEN, "backend/tests/fixtures/db has no frozen release database (scripts/freeze_release_db.py)"


@pytest.mark.asyncio
@pytest.mark.parametrize("sql_file", FROZEN, ids=lambda p: p.stem)
async def test_release_database_upgrades_to_current_schema(sql_file, tmp_path, docker_unavailable, caplog):
    db_path = tmp_path / "gravitylan.db"
    _restore(sql_file, db_path)
    before = _row_counts(db_path)

    with caplog.at_level(logging.ERROR, logger="app.database.migrations"):
        await _start_like_main(db_path, tmp_path / "telemetry.db")

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []

    # create_all never adds a column to an existing table: each new model column needs an entry in MIGRATIONS
    columns = _columns(db_path)
    missing = {
        table.name: sorted({c.name for c in table.columns} - columns.get(table.name, set()))
        for table in INVENTORY_TABLES
    }
    assert {t: cols for t, cols in missing.items() if cols} == {}, "model columns without a migration"

    after = _row_counts(db_path)
    assert {t: n for t, n in before.items() if after.get(t) != n} == {}, "the upgrade lost rows"


def _empty_instance(db_path: Path) -> None:
    """A freshly set-up instance: full inventory schema, its own credentials, nothing else."""
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine, tables=INVENTORY_TABLES)
    engine.dispose()
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO app_settings (key, value, category) VALUES (?, ?, 'system')",
            [("setup.complete", "true"), ("api.master_token", "test-admin-token-12345"),
             ("api.admin_password", "$argon2id$other-hash")],
        )
        conn.commit()
    finally:
        conn.close()


async def _export(client, admin_token, db_path: Path, monkeypatch) -> dict:
    monkeypatch.setattr(app_config, "database_url", f"sqlite+aiosqlite:///{db_path}")
    response = await client.get("/api/backup/export", headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200
    body = response.json()
    body.pop("metadata")
    body["settings"] = sorted(
        ({k: v for k, v in row.items() if k != "id"} for row in body["settings"] if row["key"] not in PROTECTED),
        key=lambda row: row["key"],
    )
    return body


@pytest.mark.asyncio
@pytest.mark.skipif(not FROZEN, reason="no frozen release database")
async def test_backup_roundtrip_onto_a_fresh_host(client, admin_token, tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    _restore(FROZEN[-1], source)
    exported = await _export(client, admin_token, source, monkeypatch)
    assert exported["devices"], "the frozen database should carry devices"

    fresh = tmp_path / "fresh.db"
    _empty_instance(fresh)
    backup._write_db(str(fresh), {**exported, "metadata": {"version": app_config.app_version}})

    assert await _export(client, admin_token, fresh, monkeypatch) == exported
