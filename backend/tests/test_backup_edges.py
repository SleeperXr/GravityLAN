"""Edges of backup export and import (app/api/backup.py): failing caches, missing files and tables,
unauthorized keys, rejected uploads and the texts of an import."""

import logging
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api import backup
from app.api.topology import topology_cache
from app.config import settings as app_config
from app.database import Base
from app.models.agent import AgentToken
from app.models.device import Device
from app.models.setting import Setting


@pytest.fixture
def backup_db(tmp_path, monkeypatch):
    path = tmp_path / "gravitylan.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.schema is None])
    with Session(engine) as s:
        s.add(Setting(key="scan_interval", value="5"))
        s.add(Device(id=1, ip="192.0.2.1", display_name="nas"))
        s.flush()
        s.add(AgentToken(device_id=1, token="synthetic-agent-token"))
        s.commit()
    engine.dispose()
    monkeypatch.setattr(app_config, "database_url", f"sqlite+aiosqlite:///{path}")
    return str(path)


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def query(db_path, sql):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def execute(db_path, sql):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


async def upload(client, auth, payload: bytes, name="backup.json"):
    return await client.post("/api/backup/import", files={"file": (name, payload, "application/json")}, headers=auth)


def test_one_failing_cache_does_not_stop_the_others(caplog):
    broken = SimpleNamespace(clear=lambda: (_ for _ in ()).throw(RuntimeError("cache down")))
    topology_cache["key"] = {"nodes": []}
    with patch("app.api.devices.dashboard_cache", broken), caplog.at_level(logging.WARNING, logger="app.api.backup"):
        backup.invalidate_all_runtime_caches()
    assert "Could not clear dashboard_cache: cache down" in caplog.text
    assert len(topology_cache) == 0


async def test_export_without_a_database_file_is_404(client, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "database_url", f"sqlite+aiosqlite:///{tmp_path / 'missing.db'}")
    assert (await client.get("/api/backup/export", headers=auth)).status_code == 404


async def test_export_skips_a_missing_table(client, auth, backup_db):
    execute(backup_db, "DROP TABLE rack_cables")
    res = await client.get("/api/backup/export", headers=auth)
    assert res.status_code == 200
    assert "rack_cables" not in res.json()
    assert [d["ip"] for d in res.json()["devices"]] == ["192.0.2.1"]


async def test_export_leaves_out_the_instance_credentials(client, auth, backup_db):
    # A backup file must not carry a working master token or the password hash
    execute(backup_db, "INSERT INTO app_settings(key, value, category) VALUES "
                       "('api.master_token', 'synthetic-master', 'general'), "
                       "('api.admin_password', '$argon2id$synthetic', 'system'), "
                       "('setup.complete', 'true', 'system')")
    res = await client.get("/api/backup/export", headers=auth)
    assert res.status_code == 200
    keys = {row["key"] for row in res.json()["settings"]}
    assert keys == {"scan_interval"}


async def test_export_failure_is_a_500(client, auth, backup_db):
    with patch("app.api.backup.audit", new=AsyncMock(side_effect=RuntimeError("audit down"))):
        res = await client.get("/api/backup/export", headers=auth)
    assert res.status_code == 500


def test_rack_cleanup_does_nothing_on_a_database_without_rack_tables():
    conn = sqlite3.connect(":memory:")
    try:
        backup._drop_orphaned_rack_rows(conn.cursor())
    finally:
        conn.close()


def test_unauthorized_keys_are_not_imported(backup_db):
    imported = backup._write_db(backup_db, {"agent_tokens": [{"device_id": 1, "token": "from-backup"}]})
    assert imported == {}
    assert query(backup_db, "SELECT token FROM agent_tokens") == [("synthetic-agent-token",)]


def test_a_change_to_protected_settings_rolls_everything_back(backup_db):
    with patch("app.api.backup._read_protected_settings", side_effect=[{"setup.complete": "true"}, {}]), \
            pytest.raises(RuntimeError, match="protected settings"):
        backup._write_db(backup_db, {"settings": [{"key": "scan_interval", "value": "99"}]})
    assert query(backup_db, "SELECT value FROM app_settings WHERE key = 'scan_interval'") == [("5",)]


async def test_upload_must_be_a_json_file(client, auth, backup_db):
    res = await upload(client, auth, b"{}", name="backup.txt")
    assert res.status_code == 400
    assert res.json()["detail"] == "Only JSON files are supported"


async def test_upload_over_the_limit_is_refused(client, auth, backup_db, monkeypatch):
    monkeypatch.setattr(backup, "MAX_BACKUP_BYTES", 8)
    res = await upload(client, auth, b'{"settings": []}')
    assert res.status_code == 413
    assert query(backup_db, "SELECT ip FROM devices") == [("192.0.2.1",)]


def test_import_message_names_revoked_agents_and_skipped_duplicates():
    assert backup._import_message(0, 0) == "Backup successfully imported"
    assert "2 agent(s)" in backup._import_message(2, 0)
    assert "1 duplicate entry was skipped" in backup._import_message(0, 1)
    assert "3 duplicate entries were skipped" in backup._import_message(0, 3)


def test_audit_detail_mentions_duplicates_only_when_there_are_some():
    imported = {"devices": 2, "app_settings": 5}
    assert backup._import_audit_detail(imported, 0) == "2 devices, 5 settings"
    assert backup._import_audit_detail(imported, 4) == "2 devices, 5 settings, 4 duplicates skipped"


async def test_a_failing_telemetry_table_does_not_stop_the_purge(caplog):
    db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("telemetry down")), commit=AsyncMock())
    with caplog.at_level(logging.WARNING, logger="app.api.backup"):
        await backup._purge_telemetry(db, [1])
    assert db.execute.await_count >= 2
    db.commit.assert_awaited_once()
    assert "telemetry down" in caplog.text
