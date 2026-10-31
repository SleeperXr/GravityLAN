"""Backup import: protected settings, excluded agent tokens, all-or-nothing transaction."""

import json
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import backup
from app.config import settings as app_config
from app.database import Base
from app.models.agent import AgentToken
from app.models.device import Device, DeviceGroup
from app.models.setting import Setting

PROTECTED = {
    "api.master_token": "current-master-token",
    "api.admin_password": "$argon2id$current-hash",
    "setup.complete": "true",
}


@pytest.fixture
def backup_db(tmp_path):
    """A file-based SQLite database with the full schema and a running instance's state."""
    path = tmp_path / "gravitylan.db"
    engine = create_engine(f"sqlite:///{path}")
    # Inventory tables only: the measurement tables live in the separate telemetry.db
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.schema is None])
    with Session(engine) as s:
        for key, value in PROTECTED.items():
            s.add(Setting(key=key, value=value))
        s.add(Setting(key="scan_interval", value="5"))
        s.add(DeviceGroup(id=1, name="Servers"))
        s.add(Device(id=1, ip="10.0.0.1", display_name="nas"))
        s.flush()
        s.add(AgentToken(device_id=1, token="live-agent-token"))
        s.commit()
    engine.dispose()
    return str(path)


def _query(db_path, sql):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _settings(db_path) -> dict:
    return dict(_query(db_path, "SELECT key, value FROM app_settings"))


def test_agent_tokens_not_importable():
    assert "agent_tokens" not in backup.ALLOWED_TABLE_MAP


def test_import_keeps_protected_settings(backup_db):
    data = {
        "settings": [
            # ids collide with the protected rows that stay in the table
            {"id": 1, "key": "api.master_token", "value": "attacker-token", "category": "general"},
            {"id": 2, "key": "api.admin_password", "value": "", "category": "system"},
            {"id": 3, "key": "setup.complete", "value": "false", "category": "system"},
            {"id": 4, "key": "scan_interval", "value": "30", "category": "scan"},
            {"id": 5, "key": "theme", "value": "dark", "category": "ui"},
        ],
    }

    backup._write_db(backup_db, data)

    stored = _settings(backup_db)
    for key, value in PROTECTED.items():
        assert stored[key] == value
    assert stored["scan_interval"] == "30"
    assert stored["theme"] == "dark"


def test_import_without_protected_keys_does_not_delete_them(backup_db):
    backup._write_db(backup_db, {"settings": [{"key": "scan_interval", "value": "15", "category": "scan"}]})

    stored = _settings(backup_db)
    for key, value in PROTECTED.items():
        assert stored[key] == value
    assert stored["scan_interval"] == "15"


def test_import_ignores_agent_tokens(backup_db):
    data = {
        "devices": [{"id": 1, "ip": "10.0.0.1", "display_name": "nas"}],
        "agent_tokens": [{"id": 99, "device_id": 1, "token": "stolen-token", "is_active": 1}],
    }

    imported = backup._write_db(backup_db, data)

    assert "agent_tokens" not in imported
    assert _query(backup_db, "SELECT token FROM agent_tokens") == [("live-agent-token",)]


def test_failed_import_rolls_back_everything(backup_db):
    data = {
        # Processed first: deleted and re-inserted before the error below
        "device_groups": [{"id": 10, "name": "Replaced"}],
        "settings": [{"key": "scan_interval", "value": "99", "category": "scan"}],
        # Duplicate unique ip -> IntegrityError halfway through the import
        "devices": [
            {"id": 2, "ip": "10.0.0.2", "display_name": "a"},
            {"id": 3, "ip": "10.0.0.2", "display_name": "b"},
        ],
    }

    with pytest.raises(sqlite3.IntegrityError):
        backup._write_db(backup_db, data)

    assert _query(backup_db, "SELECT name FROM device_groups") == [("Servers",)]
    assert _query(backup_db, "SELECT ip FROM devices") == [("10.0.0.1",)]
    assert _settings(backup_db)["scan_interval"] == "5"
    # The database is not left locked by an open transaction
    backup._write_db(backup_db, {"settings": [{"key": "scan_interval", "value": "7", "category": "scan"}]})
    assert _settings(backup_db)["scan_interval"] == "7"


# --- endpoint -----------------------------------------------------------------

@pytest.fixture
def import_endpoint_db(backup_db, monkeypatch):
    monkeypatch.setattr(app_config, "database_url", f"sqlite+aiosqlite:///{backup_db}")
    return backup_db


async def _post_backup(client, admin_token, payload: bytes):
    return await client.post(
        "/api/backup/import",
        files={"file": ("backup.json", payload, "application/json")},
        headers={"Authorization": f"Bearer {admin_token}"},
    )


@pytest.mark.asyncio
async def test_import_endpoint_success(client, admin_token, import_endpoint_db):
    payload = json.dumps({
        "metadata": {"version": "0.1.0"},
        "settings": [{"key": "api.master_token", "value": "attacker"}, {"key": "scan_interval", "value": "20"}],
    }).encode()

    response = await _post_backup(client, admin_token, payload)

    assert response.status_code == 200
    stored = _settings(import_endpoint_db)
    assert stored["api.master_token"] == PROTECTED["api.master_token"]
    assert stored["scan_interval"] == "20"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"not json", b"[1, 2]", b'{"devices": {"ip": "x"}}', b'{"devices": [1]}'])
async def test_import_endpoint_rejects_malformed_backup(client, admin_token, import_endpoint_db, payload):
    response = await _post_backup(client, admin_token, payload)
    assert response.status_code == 400
    assert _query(import_endpoint_db, "SELECT ip FROM devices") == [("10.0.0.1",)]


@pytest.mark.asyncio
async def test_import_endpoint_failure_leaves_database_unchanged(client, admin_token, import_endpoint_db):
    payload = json.dumps({
        "device_groups": [{"id": 10, "name": "Replaced"}],
        "devices": [{"id": 2, "ip": "10.0.0.2"}, {"id": 3, "ip": "10.0.0.2"}],
    }).encode()

    response = await _post_backup(client, admin_token, payload)

    assert response.status_code == 500
    assert "no changes were made" in response.json()["detail"]
    assert _query(import_endpoint_db, "SELECT name FROM device_groups") == [("Servers",)]



@pytest.mark.asyncio
async def test_export_and_import_preserves_device_interfaces_and_clears_stale_ones(client, admin_token, import_endpoint_db):
    conn = sqlite3.connect(import_endpoint_db)
    try:
        conn.execute(
            "INSERT INTO device_interfaces (id, device_id, ip, mac, label, is_online) VALUES (1, 1, '192.168.110.1', 'aa:bb:cc:00:00:01', 'VLAN 110', 1)"
        )
        conn.commit()
    finally:
        conn.close()

    exported = await client.get("/api/backup/export", headers={"Authorization": f"Bearer {admin_token}"})
    assert exported.status_code == 200
    body = exported.json()
    assert body["metadata"]["version"] == app_config.app_version
    assert len(body["device_interfaces"]) == 1
    assert body["device_interfaces"][0]["ip"] == "192.168.110.1"

    # Importing a backup that replaces devices without interfaces clears stale device_interfaces
    backup._write_db(import_endpoint_db, {"devices": [{"id": 2, "ip": "10.0.0.99", "display_name": "router"}]})
    assert _query(import_endpoint_db, "SELECT ip FROM device_interfaces") == []

    # Importing the exported backup restores the device and its interface
    backup._write_db(import_endpoint_db, body)
    assert _query(import_endpoint_db, "SELECT device_id, ip, label FROM device_interfaces") == [(1, "192.168.110.1", "VLAN 110")]


# --- rack cabling ---------------------------------------------------------------

def _seed_rack_cabling(db_path):
    """Rack 1 with a patch panel; the panel's port 1 is cabled to port 1 of device 1."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            INSERT INTO racks (id, name, units, width) VALUES (1, 'A', 12, 19);
            INSERT INTO rack_items (id, rack_id, name, kind, rack_unit, rack_height) VALUES (1, 1, 'Panel', 'patch_panel', 11, 1);
            INSERT INTO rack_ports (id, rack_item_id, number, kind, side) VALUES (1, 1, 1, 'RJ45', 'front');
            INSERT INTO rack_ports (id, device_id, number, kind, side) VALUES (2, 1, 1, 'RJ45', 'rear');
            INSERT INTO rack_cables (id, a_port_id, b_port_id, cable, color) VALUES (1, 1, 2, 'Cat6', '#3b82f6');
        """)
        conn.commit()
    finally:
        conn.close()


def _rack_rows(db_path):
    return {
        "items": _query(db_path, "SELECT id, rack_id, name FROM rack_items"),
        "ports": _query(db_path, "SELECT id, device_id, rack_item_id FROM rack_ports ORDER BY id"),
        "cables": _query(db_path, "SELECT id, a_port_id, b_port_id, color FROM rack_cables"),
    }


@pytest.mark.asyncio
async def test_rack_cabling_survives_export_and_import(client, admin_token, import_endpoint_db):
    _seed_rack_cabling(import_endpoint_db)
    before = _rack_rows(import_endpoint_db)

    exported = await client.get("/api/backup/export", headers={"Authorization": f"Bearer {admin_token}"})
    body = exported.json()
    assert len(body["rack_items"]) == 1 and len(body["rack_ports"]) == 2 and len(body["rack_cables"]) == 1

    conn = sqlite3.connect(import_endpoint_db)
    conn.executescript("DELETE FROM rack_cables; DELETE FROM rack_ports; DELETE FROM rack_items;")
    conn.close()
    backup._write_db(import_endpoint_db, body)

    assert _rack_rows(import_endpoint_db) == before


def test_backup_with_empty_rack_lists_empties_them(backup_db):
    _seed_rack_cabling(backup_db)

    imported = backup._write_db(backup_db, {"rack_items": [], "rack_ports": [], "rack_cables": []})

    assert imported == {"rack_items": 0, "rack_ports": 0, "rack_cables": 0}
    assert _rack_rows(backup_db) == {"items": [], "ports": [], "cables": []}
    assert _query(backup_db, "SELECT name FROM racks") == [("A",)]


def test_older_backup_keeps_cabling_of_the_same_device(backup_db):
    _seed_rack_cabling(backup_db)
    before = _rack_rows(backup_db)

    backup._write_db(backup_db, {"devices": [{"id": 1, "ip": "10.0.0.1", "display_name": "nas"}]})

    assert _rack_rows(backup_db) == before


def test_older_backup_drops_cabling_of_a_reassigned_device(backup_db):
    _seed_rack_cabling(backup_db)

    # Id 1 now names another device (#47): its port and the cable on it belonged to the old one
    backup._write_db(backup_db, {"devices": [{"id": 1, "ip": "10.0.0.50", "display_name": "printer"}]})

    rows = _rack_rows(backup_db)
    assert rows["ports"] == [(1, None, 1)]
    assert rows["cables"] == []
    assert rows["items"] == [(1, 1, "Panel")]


def test_replaced_racks_drop_items_on_racks_that_are_gone(backup_db):
    _seed_rack_cabling(backup_db)

    backup._write_db(backup_db, {"racks": [{"id": 2, "name": "B", "units": 42, "width": 19}]})

    rows = _rack_rows(backup_db)
    assert rows["items"] == []
    assert rows["ports"] == [(2, 1, None)]
    assert rows["cables"] == []


# --- restore in the setup wizard -------------------------------------------------

def _backup_payload() -> bytes:
    return json.dumps({
        "metadata": {"version": "0.6.0"},
        "devices": [{"id": 7, "ip": "10.0.0.7", "display_name": "nas-from-backup"}],
        "subnets": [{"id": 3, "cidr": "10.0.0.0/24", "name": "LAN", "is_enabled": 1}],
        "settings": [
            {"key": "api.admin_password", "value": "$argon2id$from-another-instance"},
            {"key": "setup.complete", "value": "true"},
            {"key": "scan_interval", "value": "15"},
        ],
    }).encode()


@pytest.fixture
def fresh_instance_db(backup_db, monkeypatch):
    """A file database before setup: no credentials and no setup state yet."""
    _query(backup_db, "SELECT 1")
    conn = sqlite3.connect(backup_db)
    conn.execute("DELETE FROM app_settings")
    conn.commit()
    conn.close()
    monkeypatch.setattr(app_config, "database_url", f"sqlite+aiosqlite:///{backup_db}")
    return backup_db


@pytest.mark.asyncio
async def test_setup_wizard_restores_a_backup_without_its_credentials(client, fresh_instance_db):
    res = await client.post("/api/setup/restore", files={"file": ("backup.json", _backup_payload(), "application/json")})

    assert res.status_code == 200, res.text
    assert res.json()["devices"] == 1
    assert _query(fresh_instance_db, "SELECT display_name FROM devices") == [("nas-from-backup",)]
    stored = _settings(fresh_instance_db)
    # The wizard sets its own password next; the setup stays open until it does
    assert "api.admin_password" not in stored and "setup.complete" not in stored
    assert stored["scan_interval"] == "15"


@pytest.mark.asyncio
async def test_setup_restore_is_closed_once_the_setup_is_done(client, admin_token, fresh_instance_db):
    res = await client.post("/api/setup/restore", files={"file": ("backup.json", _backup_payload(), "application/json")})
    assert res.status_code == 403
    assert _query(fresh_instance_db, "SELECT ip FROM devices") == [("10.0.0.1",)]


@pytest.mark.asyncio
async def test_completing_a_restored_setup_keeps_its_subnets(client, db, monkeypatch):
    from app.models.network import Subnet
    from sqlalchemy import select as sa_select
    db.add(Subnet(cidr="10.0.0.0/24", name="LAN from backup"))
    await db.commit()
    detected = []
    monkeypatch.setattr("app.scanner.utils.get_local_subnets", lambda: detected.append(1) or [])

    res = await client.post("/api/setup/complete", json={"admin_password": "new-password-123", "restored": True})

    assert res.status_code == 200 and res.json()["devices_adopted"] == 0
    assert detected == []  # no local networks were added on top
    assert [s.cidr for s in (await db.execute(sa_select(Subnet))).scalars()] == ["10.0.0.0/24"]
