"""Old databases get the unique keys of the models: duplicates go (newest kept), then the index is added."""

import logging
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, attach_telemetry_database
from app.database.migrations import run_migrations, unique_column_sets

FROZEN_SQL = Path(__file__).parent / "fixtures" / "db" / "gravitylan-0.6.0.sql"

# Tables as they looked before their unique constraint existed
OLD_SCHEMA = """
    DROP TABLE topology_links;
    CREATE TABLE topology_links (
        id INTEGER NOT NULL PRIMARY KEY, source_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
        source_handle VARCHAR(20), target_handle VARCHAR(20), link_type VARCHAR(50) NOT NULL,
        speed INTEGER, color VARCHAR(7), notes TEXT, role VARCHAR(20) DEFAULT 'primary' NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        FOREIGN KEY(source_id) REFERENCES devices (id) ON DELETE CASCADE,
        FOREIGN KEY(target_id) REFERENCES devices (id) ON DELETE CASCADE
    );
    INSERT INTO topology_links (id, source_id, target_id, link_type) VALUES (1, 1, 2, '1GbE');
    INSERT INTO topology_links (id, source_id, target_id, link_type) VALUES (2, 1, 2, '10GbE');
    INSERT INTO topology_links (id, source_id, target_id, link_type) VALUES (3, 1, 3, '1GbE');

    DROP TABLE rack_cables; DROP TABLE rack_ports; DROP TABLE rack_items; DROP TABLE racks;
    CREATE TABLE racks (
        id INTEGER NOT NULL PRIMARY KEY, name VARCHAR(100) NOT NULL, units INTEGER NOT NULL,
        width INTEGER NOT NULL, notes TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    );
    INSERT INTO racks (id, name, units, width) VALUES (1, 'Keller', 12, 19);
    INSERT INTO racks (id, name, units, width) VALUES (2, 'Keller', 42, 19);
"""


def _old_database(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(FROZEN_SQL.read_text(encoding="utf-8"))
        conn.executescript(OLD_SCHEMA)
    finally:
        conn.close()


async def _start(db_path: Path, telemetry_path: Path) -> None:
    """create_all, then run_migrations, with foreign keys on like the app's engine."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    @event.listens_for(engine.sync_engine, "connect")
    def _connect(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        attach_telemetry_database(dbapi_connection, str(telemetry_path))

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as db:
            await run_migrations(db)
    finally:
        await engine.dispose()


def _query(db_path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def docker_unavailable(monkeypatch):
    docker_service = MagicMock()
    docker_service.is_available.return_value = False
    monkeypatch.setattr("app.services.docker_service.docker_service", docker_service)


def test_unique_column_sets_come_from_the_models():
    assert unique_column_sets("topology_links") == [("source_id", "target_id")]
    assert unique_column_sets("rack_ports") == [("device_id", "number"), ("rack_item_id", "number")]
    assert unique_column_sets("racks") == [("name",)]
    assert unique_column_sets("no_such_table") == []


@pytest.mark.asyncio
async def test_old_database_loses_duplicates_and_gains_unique_indexes(tmp_path, caplog):
    db_path = tmp_path / "gravitylan.db"
    _old_database(db_path)

    with caplog.at_level(logging.INFO, logger="app.database.migrations"):
        await _start(db_path, tmp_path / "telemetry.db")

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
    # The newest row of each key is kept; unrelated rows stay
    assert _query(db_path, "SELECT id, link_type FROM topology_links ORDER BY id") == [(2, "10GbE"), (3, "1GbE")]
    assert _query(db_path, "SELECT id, units FROM racks") == [(2, 42)]
    assert "duplicate row(s) removed" in caplog.text

    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO topology_links (source_id, target_id, link_type) VALUES (1, 2, 'WLAN')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO racks (name, units, width) VALUES ('Keller', 12, 19)")
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_removing_a_duplicate_cascades_to_its_rows(tmp_path):
    db_path = tmp_path / "gravitylan.db"
    _old_database(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE rack_items (
                id INTEGER NOT NULL PRIMARY KEY, rack_id INTEGER NOT NULL, name VARCHAR(100) NOT NULL,
                kind VARCHAR(40) NOT NULL, rack_unit INTEGER, rack_height INTEGER NOT NULL, notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                FOREIGN KEY(rack_id) REFERENCES racks (id) ON DELETE CASCADE
            );
            INSERT INTO rack_items (id, rack_id, name, kind, rack_height) VALUES (1, 1, 'Old panel', 'patch_panel', 1);
            INSERT INTO rack_items (id, rack_id, name, kind, rack_height) VALUES (2, 2, 'Panel', 'patch_panel', 1);
        """)
    finally:
        conn.close()

    await _start(db_path, tmp_path / "telemetry.db")

    assert _query(db_path, "SELECT id, rack_id FROM rack_items") == [(2, 2)]


@pytest.mark.asyncio
async def test_rows_with_an_empty_key_column_are_not_duplicates(tmp_path):
    db_path = tmp_path / "gravitylan.db"
    _old_database(db_path)
    conn = sqlite3.connect(db_path)
    try:
        # rack_ports before its unique keys: ports of rack items leave device_id empty, so (device_id, number)
        # repeats as (NULL, 1) without being a duplicate; (device_id, number) = (1, 1) twice is one
        conn.executescript("""
            CREATE TABLE rack_items (
                id INTEGER NOT NULL PRIMARY KEY, rack_id INTEGER NOT NULL, name VARCHAR(100) NOT NULL,
                kind VARCHAR(40) NOT NULL, rack_unit INTEGER, rack_height INTEGER NOT NULL, notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            CREATE TABLE rack_ports (
                id INTEGER NOT NULL PRIMARY KEY, device_id INTEGER, rack_item_id INTEGER,
                number INTEGER NOT NULL, kind VARCHAR(20) NOT NULL, side VARCHAR(10) DEFAULT 'front' NOT NULL
            );
            INSERT INTO rack_items (id, rack_id, name, kind, rack_height) VALUES (1, 2, 'A', 'patch_panel', 1);
            INSERT INTO rack_items (id, rack_id, name, kind, rack_height) VALUES (2, 2, 'B', 'patch_panel', 1);
            INSERT INTO rack_ports (id, rack_item_id, number, kind) VALUES (1, 1, 1, 'RJ45');
            INSERT INTO rack_ports (id, rack_item_id, number, kind) VALUES (2, 2, 1, 'RJ45');
            INSERT INTO rack_ports (id, device_id, number, kind) VALUES (3, 1, 1, 'RJ45');
            INSERT INTO rack_ports (id, device_id, number, kind) VALUES (4, 1, 1, 'SFP+');
        """)
    finally:
        conn.close()

    await _start(db_path, tmp_path / "telemetry.db")

    assert _query(db_path, "SELECT id FROM rack_ports ORDER BY id") == [(1,), (2,), (4,)]


@pytest.mark.asyncio
async def test_a_current_database_is_left_untouched(tmp_path, caplog):
    db_path = tmp_path / "gravitylan.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(FROZEN_SQL.read_text(encoding="utf-8"))
    finally:
        conn.close()
    indexes_before = _query(db_path, "SELECT name FROM sqlite_master WHERE type = 'index' ORDER BY name")

    with caplog.at_level(logging.INFO, logger="app.database.migrations"):
        await _start(db_path, tmp_path / "telemetry.db")
        await _start(db_path, tmp_path / "telemetry.db")

    assert "Unique index on" not in caplog.text
    indexes_after = _query(db_path, "SELECT name FROM sqlite_master WHERE type = 'index' ORDER BY name")
    assert [n for n in indexes_after if n[0].startswith("uix_")] == [
        n for n in indexes_before if n[0].startswith("uix_")
    ]
