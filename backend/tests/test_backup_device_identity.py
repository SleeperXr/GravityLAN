"""Backup import drops device-bound rows whose device id now names another device (#47)."""
import json
import sqlite3

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import backup
from app.database import Base
from app.models.agent import AgentToken
from app.models.device import Device, DeviceHistory, DeviceInterface
from app.models.ssh import SshProfile
from app.models.setting import Setting

from tests.test_backup_import import _post_backup, _query, backup_db, import_endpoint_db  # noqa: F401  (fixtures)


@pytest.fixture
def instance_db(tmp_path):
    """Device 1 = server A with an agent, device 2 = NAS, both with interfaces, history and a saved SSH connection."""
    path = tmp_path / "gravitylan.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.schema is None])
    with Session(engine) as s:
        s.add(Setting(key="setup.complete", value="true"))
        s.add(Device(id=1, ip="10.0.0.1", mac="AA:AA:AA:AA:AA:01", display_name="server-a"))
        s.add(Device(id=2, ip="10.0.0.2", mac="", display_name="nas"))
        s.flush()
        s.add(AgentToken(device_id=1, token="sha256:server-a"))
        s.add(AgentToken(device_id=2, token="sha256:nas"))
        for device_id in (1, 2):
            s.add(DeviceInterface(device_id=device_id, mac=f"bb:bb:bb:bb:bb:0{device_id}", ip=f"10.0.0.{device_id}"))
            s.add(DeviceHistory(device_id=device_id, status="online"))
            s.add(SshProfile(name=f"login-{device_id}", host=f"10.0.0.{device_id}", port=22, username="root",
                             auth_method="password", device_id=device_id))
        s.commit()
    engine.dispose()
    return str(path)


def _rows(db_path, sql):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_backup_of_another_instance_revokes_agents_of_reassigned_ids(instance_db):
    report: dict = {}
    # Foreign backup: id 1 is now server B (other MAC), id 2 is still the NAS (no MAC, same IP)
    backup._write_db(instance_db, {"devices": [
        {"id": 1, "ip": "10.0.0.1", "mac": "cc:cc:cc:cc:cc:01", "display_name": "server-b"},
        {"id": 2, "ip": "10.0.0.2", "mac": "", "display_name": "nas"},
    ]}, report)

    assert report == {"agent_tokens_revoked": 1, "reassigned_device_ids": [1], "duplicates_dropped": {}}
    assert _rows(instance_db, "SELECT device_id, token FROM agent_tokens") == [(2, "sha256:nas")]
    assert _rows(instance_db, "SELECT device_id FROM device_interfaces") == [(2,)]
    assert _rows(instance_db, "SELECT device_id FROM device_history") == [(2,)]
    # Saved connections stay, but the one of server A no longer belongs to device 1
    assert sorted(_rows(instance_db, "SELECT name, device_id FROM ssh_profiles")) == [("login-1", None), ("login-2", 2)]


def test_restore_of_same_instance_keeps_everything(instance_db):
    report: dict = {}
    backup._write_db(instance_db, {"devices": [
        {"id": 1, "ip": "10.0.0.50", "mac": "aa:aa:aa:aa:aa:01", "display_name": "server-a"},  # new IP, same MAC
        {"id": 2, "ip": "10.0.0.2", "mac": "", "display_name": "nas"},
    ]}, report)

    assert report == {"agent_tokens_revoked": 0, "reassigned_device_ids": [], "duplicates_dropped": {}}
    assert len(_rows(instance_db, "SELECT * FROM agent_tokens")) == 2
    assert len(_rows(instance_db, "SELECT * FROM device_interfaces")) == 2


def test_devices_missing_from_backup_lose_their_rows(instance_db):
    report: dict = {}
    backup._write_db(instance_db, {"devices": [
        {"id": 2, "ip": "10.0.0.2", "mac": "", "display_name": "nas"},
    ]}, report)

    assert report["reassigned_device_ids"] == [1]
    assert _rows(instance_db, "SELECT device_id FROM agent_tokens") == [(2,)]


def test_import_without_devices_changes_nothing(instance_db):
    report: dict = {}
    backup._write_db(instance_db, {"settings": [{"key": "scan_interval", "value": "5", "category": "scan"}]}, report)
    assert report == {"agent_tokens_revoked": 0, "reassigned_device_ids": [], "duplicates_dropped": {}}


@pytest.mark.asyncio
async def test_import_endpoint_reports_revoked_agents(client, admin_token, import_endpoint_db):
    payload = json.dumps({"devices": [{"id": 1, "ip": "10.0.0.9", "display_name": "other host"}]}).encode()

    response = await _post_backup(client, admin_token, payload)

    assert response.status_code == 200
    body = response.json()
    assert body["agent_tokens_revoked"] == 1
    assert body["reassigned_devices"] == 1
    assert "enrolled again" in body["message"]
    assert _query(import_endpoint_db, "SELECT * FROM agent_tokens") == []


@pytest.mark.asyncio
async def test_purge_telemetry_removes_measurements_of_reassigned_ids(db):
    from sqlalchemy import func, select
    from app.models.agent import DeviceMetrics

    db.add_all([DeviceMetrics(device_id=1, cpu_percent=5.0), DeviceMetrics(device_id=2, cpu_percent=7.0)])
    await db.commit()

    await backup._purge_telemetry(db, [1])

    remaining = (await db.execute(select(DeviceMetrics.device_id, func.count()).group_by(DeviceMetrics.device_id))).all()
    assert remaining == [(2, 1)]


def test_unlinked_connections_keep_the_old_device_address(instance_db):
    # A connection or history entry bound to a device has no host of its own (#47 follow-up)
    conn = sqlite3.connect(instance_db)
    conn.execute("UPDATE ssh_profiles SET host = NULL")
    conn.execute("INSERT INTO ssh_history (device_id, host, port, username, auth_method) VALUES (1, NULL, 22, 'root', 'password')")
    conn.commit()
    conn.close()

    backup._write_db(instance_db, {"devices": [
        {"id": 1, "ip": "10.0.0.1", "mac": "cc:cc:cc:cc:cc:01", "display_name": "server-b"},
        {"id": 2, "ip": "10.0.0.2", "mac": "", "display_name": "nas"},
    ]}, {})

    assert sorted(_rows(instance_db, "SELECT name, device_id, host FROM ssh_profiles")) == [
        ("login-1", None, "10.0.0.1"), ("login-2", 2, None),
    ]
    assert _rows(instance_db, "SELECT device_id, host FROM ssh_history") == [(None, "10.0.0.1")]


def test_unlinking_keeps_an_explicit_host(instance_db):
    conn = sqlite3.connect(instance_db)
    conn.execute("UPDATE ssh_profiles SET host = 'server-a.lan' WHERE device_id = 1")
    conn.commit()
    conn.close()

    backup._write_db(instance_db, {"devices": [{"id": 1, "ip": "10.0.0.9", "mac": "cc:cc:cc:cc:cc:01"}]}, {})

    assert _rows(instance_db, "SELECT host FROM ssh_profiles WHERE name = 'login-1'") == [("server-a.lan",)]


class _FakeSocket:
    def __init__(self):
        self.closed_with = None

    async def close(self, code: int = 1000, reason: str | None = None):
        self.closed_with = code

    async def send_text(self, text: str):
        pass

    async def send_json(self, data):
        pass


@pytest.mark.asyncio
async def test_import_revokes_install_codes_and_streams_of_reassigned_ids(monkeypatch):
    from app.api.agent_patches import _temp_patch_tokens
    from app.services.agent_telemetry import _ws_subscribers
    from app.services.enrollment_service import enrollment_store

    old_code, kept_code = enrollment_store.issue(1), enrollment_store.issue(2)
    monkeypatch.setitem(_temp_patch_tokens, "patch-1", {"device_id": 1, "created_at": 0})
    monkeypatch.setitem(_temp_patch_tokens, "patch-2", {"device_id": 2, "created_at": 0})
    stream_1, stream_2 = _FakeSocket(), _FakeSocket()
    monkeypatch.setitem(_ws_subscribers, 1, {stream_1})
    monkeypatch.setitem(_ws_subscribers, 2, {stream_2})

    await backup._revoke_device_grants([1])

    # A code issued for server A must not enroll an agent token for server B
    assert not enrollment_store.is_valid(old_code, 1)
    assert enrollment_store.is_valid(kept_code, 2)
    assert "patch-1" not in _temp_patch_tokens and "patch-2" in _temp_patch_tokens
    assert stream_1.closed_with == 4003 and 1 not in _ws_subscribers
    assert stream_2.closed_with is None and _ws_subscribers[2] == {stream_2}
    enrollment_store.consume(kept_code, 2)


@pytest.mark.asyncio
async def test_import_endpoint_revokes_install_codes_of_reassigned_ids(client, admin_token, import_endpoint_db):
    from app.services.enrollment_service import enrollment_store

    old_code = enrollment_store.issue(1)
    payload = json.dumps({"devices": [{"id": 1, "ip": "10.0.0.9", "display_name": "other host"}]}).encode()

    response = await _post_backup(client, admin_token, payload)

    assert response.status_code == 200
    assert response.json()["reassigned_devices"] == 1
    # The install command issued for the old device 1 no longer enrolls an agent for the new one
    assert not enrollment_store.is_valid(old_code, 1)


def test_backup_restores_device_interfaces_of_reassigned_ids(instance_db):
    report: dict = {}
    # Foreign backup: id 1 is server B and brings its own interface
    backup._write_db(instance_db, {
        "devices": [
            {"id": 1, "ip": "10.0.0.1", "mac": "cc:cc:cc:cc:cc:01", "display_name": "server-b"},
            {"id": 2, "ip": "10.0.0.2", "mac": "", "display_name": "nas"},
        ],
        "device_interfaces": [{"id": 7, "device_id": 1, "ip": "10.0.20.1", "mac": "cc:cc:cc:cc:cc:02"}],
    }, report)

    assert report["reassigned_device_ids"] == [1]
    assert _rows(instance_db, "SELECT device_id, ip FROM device_interfaces") == [(1, "10.0.20.1")]


def test_export_contains_device_interfaces_and_app_version(instance_db, monkeypatch):
    import asyncio
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{instance_db}")
    data = json.loads(asyncio.run(backup.export_backup(request=None)).body)
    assert data["metadata"]["version"] == settings.app_version
    assert sorted(r["ip"] for r in data["device_interfaces"]) == ["10.0.0.1", "10.0.0.2"]
