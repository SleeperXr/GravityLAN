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

    assert report == {"agent_tokens_revoked": 1, "reassigned_device_ids": [1]}
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

    assert report == {"agent_tokens_revoked": 0, "reassigned_device_ids": []}
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
    assert report == {"agent_tokens_revoked": 0, "reassigned_device_ids": []}


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
