"""What a start does when single migration steps fail, and the edge cases of the repairs around them."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Column, Index, Integer, MetaData, Table, UniqueConstraint, select

import app.database.migrations as migrations
from app.database import Base
from app.models.device import Device, Service
from app.models.setting import Setting

LOGGER = "app.database.migrations"
ALERT_REPAIR_MARKER = "migration.rc4_infra_alert_offline_repaired"

# Everything run_migrations does after the columns and the IP repair, in order, as the error log names it
REPAIR_STEPS = [
    ("app.services.agent_tokens.normalize_agent_tokens", "upgrading agent tokens"),
    ("app.database.migrations._clear_unsafe_service_links", "clearing unsafe service links"),
    ("app.database.migrations._retire_phone_system_items", "retiring phone system rack items"),
    ("app.database.migrations._add_missing_unique_indexes", "adding unique indexes"),
    ("app.database.migrations._drop_outbox_token_copies", "removing token copies from the notification outbox"),
    ("app.database.migrations._deduplicate_generic_port_services", "deduplicating generic port services"),
    ("app.database.migrations._repair_infra_alert_offline", "repairing infrastructure alert_offline flags"),
]


@pytest.fixture(autouse=True)
def docker_service(monkeypatch):
    service = MagicMock()
    service.is_available.return_value = False
    monkeypatch.setattr("app.services.docker_service.docker_service", service)
    return service


@pytest.fixture
def repair_steps(monkeypatch):
    """Replace every repair step by one that only records that it ran; the list is the order they ran in."""
    ran = []

    def recording(path):
        async def step(_db):
            ran.append(path)
        return step

    for path, _what in REPAIR_STEPS:
        monkeypatch.setattr(path, recording(path))
    return ran


def _errors(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


async def test_repair_steps_run_in_order(db, repair_steps, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await migrations.run_migrations(db)

    assert repair_steps == [path for path, _what in REPAIR_STEPS]
    assert _errors(caplog) == []
    assert "Schema migration complete." in caplog.text


@pytest.mark.parametrize("failing, what", REPAIR_STEPS)
async def test_a_failing_step_is_undone_and_the_start_goes_on(db, repair_steps, monkeypatch, caplog, failing, what):
    """Any error counts, not only database ones: one broken step must not keep the server from starting."""
    async def fails(session):
        session.add(Device(ip="10.9.9.9", display_name="half done"))
        await session.flush()
        raise RuntimeError("boom")

    monkeypatch.setattr(failing, fails)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await migrations.run_migrations(db)

    assert repair_steps == [path for path, _what in REPAIR_STEPS if path != failing]
    assert _errors(caplog) == [f"Migration error while {what}: boom"]
    assert (await db.execute(select(Device).where(Device.ip == "10.9.9.9"))).first() is None
    assert "Schema migration complete." in caplog.text


async def test_a_failing_step_keeps_the_ip_repairs(db, repair_steps, monkeypatch):
    """The IP repair is committed before the steps start, so a step's rollback cannot take it along."""
    db.add(Device(ip="offline-aa:bb:cc", ip_placeholder=True, display_name=""))
    await db.commit()

    async def fails(_session):
        raise RuntimeError("boom")

    monkeypatch.setattr(REPAIR_STEPS[0][0], fails)
    await migrations.run_migrations(db)

    db.expire_all()
    assert (await db.execute(select(Device.ip))).scalar_one() == "0.0.0.0"


async def test_a_failing_table_is_logged_without_undoing_the_others(db, repair_steps, monkeypatch, caplog):
    """The column migrations share one transaction; a rollback would take the finished tables along."""
    seen = []

    async def apply(_conn, table, _cols):
        seen.append(table)
        if table == "devices":
            raise RuntimeError("boom")

    monkeypatch.setattr(migrations, "_apply_table_migrations", apply)
    rollback = AsyncMock()
    monkeypatch.setattr(db, "rollback", rollback)
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        await migrations.run_migrations(db)

    assert set(seen) == {table for table, _column, _type in migrations.MIGRATIONS}
    assert _errors(caplog) == ["Migration error on table 'devices': boom"]
    rollback.assert_not_awaited()


async def test_a_failing_unique_index_stops_only_its_own_table(db, monkeypatch, caplog):
    monkeypatch.setattr(migrations, "_inventory_tables", lambda: ["one", "two"])
    monkeypatch.setattr(migrations, "_live_unique_sets", lambda _conn, _table: (set(), []))
    monkeypatch.setattr(migrations, "_missing_unique_sets", lambda _columns, _live, _table: [("a", "b")])

    async def deduplicate(session, table, _cols):
        session.add(Device(ip=f"10.9.9.{len(table) + (table == 'one')}", display_name=table))
        await session.flush()
        if table == "one":
            raise RuntimeError("boom")
        return 3

    monkeypatch.setattr(migrations, "_deduplicate_and_index", deduplicate)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await migrations._add_missing_unique_indexes(db)

    await db.rollback()  # what is left now was committed by the step itself
    assert (await db.execute(select(Device.display_name))).scalars().all() == ["two"]
    assert _errors(caplog) == ["Migration error while adding unique index on one(a, b): boom"]
    assert "Migration: Unique index on two(a, b) added, 3 duplicate row(s) removed" in caplog.text
    assert "Unique index on one" not in caplog.text


async def test_unique_indexes_skip_a_table_the_database_does_not_have(db, monkeypatch):
    monkeypatch.setattr(migrations, "_inventory_tables", lambda: ["no_such_table"])
    missing_sets = MagicMock()
    monkeypatch.setattr(migrations, "_missing_unique_sets", missing_sets)

    await migrations._add_missing_unique_indexes(db)

    missing_sets.assert_not_called()


@pytest.mark.parametrize("columns, live, expected", [
    ({"name"}, [], []),                           # no id to tell the newest row by
    ({"id", "units"}, [], []),                    # the key column does not exist in this table
    ({"id", "name"}, [frozenset({"name"})], []),  # already unique
    ({"id", "name"}, [], [("name",)]),
])
def test_missing_unique_sets(columns, live, expected):
    assert migrations._missing_unique_sets(columns, live, "racks") == expected


def test_unique_column_sets_have_a_fixed_order(monkeypatch):
    """Constraints by name, then unique columns, then unique indexes by name; the id is no key."""
    metadata = MetaData()
    Table(
        "t", metadata,
        Column("id", Integer, primary_key=True, unique=True),
        Column("a", Integer),
        Column("b", Integer),
        Column("c", Integer, unique=True),
        UniqueConstraint("b", "a", name="z_constraint"),
        UniqueConstraint("a", name="a_constraint"),
        Index("z_index", "a", "b", unique=True),
        Index("a_index", "b", unique=True),
        Index("plain", "c"),
    )
    monkeypatch.setattr(Base, "metadata", metadata)

    assert migrations.unique_column_sets("t") == [("c",), ("a",), ("b", "a"), ("b",), ("a", "b")]


async def test_an_in_memory_database_is_not_copied(db):
    await migrations._copy_database_once(db)

    assert "cleanup_copy_taken" not in db.info


def test_a_docker_failure_leaves_an_empty_map(docker_service, caplog):
    docker_service.is_available.return_value = True
    docker_service.get_local_containers.side_effect = RuntimeError("socket gone")

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert migrations._build_docker_container_map() == {}

    assert "socket gone" in caplog.text


@pytest.mark.parametrize("old_ip, expected", [
    (None, None),
    ("offline-aa:bb", None),
    ("not an address", None),
    ("10.0.0.9", None),  # another record has it by now
    ("10.0.0.8", "10.0.0.8"),
])
def test_restorable_old_ip(old_ip, expected):
    assert migrations._restorable_old_ip(SimpleNamespace(old_ip=old_ip), {"10.0.0.9"}) == expected


async def test_duplicate_services_keep_the_oldest_row(db, caplog):
    device = Device(ip="10.0.0.1", display_name="Box")
    db.add(device)
    await db.commit()
    db.add_all([
        Service(id=1, device_id=device.id, name="HTTP", protocol="http", port=80),
        Service(id=2, device_id=device.id, name="HTTP", protocol="http", port=80),
        Service(id=3, device_id=device.id, name="HTTPS", protocol="https", port=443),
    ])
    await db.commit()

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await migrations._deduplicate_generic_port_services(db)

    assert (await db.execute(select(Service.id).order_by(Service.id))).scalars().all() == [1, 3]
    assert "Removed 1 duplicate" in caplog.text


async def test_alert_repair_runs_only_once(db):
    db.add(Setting(key=ALERT_REPAIR_MARKER, value="true", category="system"))
    db.add(Device(ip="10.0.0.1", display_name="Box", device_type="server", alert_offline=False))
    await db.commit()

    await migrations._repair_infra_alert_offline(db)

    assert (await db.execute(select(Device.alert_offline))).scalar_one() is False


@pytest.mark.parametrize("fields, repaired", [
    ({"device_type": "server", "display_name": "Box"}, True),
    ({"device_type": "unknown", "display_name": "Box"}, True),
    *[({"device_type": kind, "display_name": "Box"}, False) for kind in ("client", "desktop", "tv", "phone", "printer")],
    ({"device_type": "DESKTOP", "display_name": "Box"}, False),
    ({"device_type": "server", "display_name": "Living-TV"}, False),
    ({"device_type": "server", "display_name": "gaming-PC"}, False),
    ({"device_type": "server", "hostname": "R123456", "display_name": "Box"}, False),  # a client host name pattern
    ({"device_type": "server", "hostname": "box", "display_name": "gaming-pc"}, True),  # the host name decides first
    ({"device_type": "desktop", "display_name": "Box", "has_agent": True}, True),  # an agent is watched 24/7
])
async def test_alert_repair_tells_clients_from_infrastructure(db, fields, repaired):
    db.add(Device(ip="10.0.0.1", alert_offline=False, **fields))
    await db.commit()

    await migrations._repair_infra_alert_offline(db)

    assert (await db.execute(select(Device.alert_offline))).scalar_one() is repaired


async def test_alert_repair_sets_its_marker_only_after_repairing(db):
    db.add(Device(ip="10.0.0.1", display_name="Box", device_type="desktop", alert_offline=False))
    await db.commit()

    await migrations._repair_infra_alert_offline(db)
    assert (await db.execute(select(Setting).where(Setting.key == ALERT_REPAIR_MARKER))).first() is None

    await db.execute(Device.__table__.update().values(device_type="server"))
    await db.commit()
    await migrations._repair_infra_alert_offline(db)

    marker = (await db.execute(select(Setting).where(Setting.key == ALERT_REPAIR_MARKER))).scalar_one()
    assert (marker.value, marker.category) == ("true", "system")
