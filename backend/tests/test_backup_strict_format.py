"""Strict backup format (AP 2): import shapes, one validation for every import path, and an export that
is complete or fails visibly (closed connections, one read snapshot).

Table key rules: ``[]`` is valid and empties the table on purpose; a list of objects is valid; anything else
(``null``, ``{}``, ``false``, ``0``, ``""``...) is refused before any data changes; a missing key keeps its table.
"""

import json
import sqlite3

import pytest
from sqlalchemy import delete, select

from app.api import backup
from app.models.audit import AuditEvent
from app.models.setting import Setting
from tests.test_backup_import import (  # noqa: F401  (fixtures)
    _post_backup,
    _query,
    _settings,
    backup_db,
    fresh_instance_db,
    import_endpoint_db,
)

# Every non-list a table key could carry; "x" and [1] cover plain wrong types and rows that are no objects
NOT_A_LIST = [None, {}, False, 0, "", "x", 5, True, {"ip": "x"}, [1], ["a"], [[]], [{}, 1]]


def _ids(values):
    return [json.dumps(v) for v in values]


def _snapshot(path) -> dict:
    """What the import must not change when it refuses a file."""
    return {
        "groups": _query(path, "SELECT id, name FROM device_groups ORDER BY id"),
        "devices": _query(path, "SELECT id, ip, display_name FROM devices ORDER BY id"),
        "settings": sorted(_settings(path).items()),
        "tokens": _query(path, "SELECT device_id, token FROM agent_tokens"),
    }


# --- the shared validation ------------------------------------------------------------------------

@pytest.mark.parametrize("value", NOT_A_LIST, ids=_ids(NOT_A_LIST))
def test_a_table_key_that_is_not_a_list_of_rows_is_refused(value):
    with pytest.raises(backup.BackupFormatError, match="'devices' must be a list of rows"):
        backup.validate_backup_payload({"devices": value})


@pytest.mark.parametrize("rows", [[], [{"id": 1}], [{"id": 1}, {"id": 2}]])
def test_an_empty_list_and_a_list_of_objects_are_valid(rows):
    backup.validate_backup_payload({"devices": rows}, require_table=True)


@pytest.mark.parametrize("root", [[], "x", 1, None, True], ids=_ids([[], "x", 1, None, True]))
def test_the_root_must_be_an_object(root):
    with pytest.raises(backup.BackupFormatError, match="expected a JSON object"):
        backup.validate_backup_payload(root)


@pytest.mark.parametrize("metadata", [None, "x", [], 0, False], ids=_ids([None, "x", [], 0, False]))
def test_metadata_must_be_an_object_when_present(metadata):
    with pytest.raises(backup.BackupFormatError, match="'metadata' must be an object"):
        backup.validate_backup_payload({"metadata": metadata, "devices": []})


def test_metadata_may_be_missing_and_unknown_keys_are_ignored():
    backup.validate_backup_payload({"devices": [], "from_a_later_version": {"anything": 1}}, require_table=True)
    backup.validate_backup_payload({"metadata": {"version": "9.9.9"}, "settings": []}, require_table=True)


def test_a_file_without_any_supported_table_is_no_backup():
    for payload in ({}, {"metadata": {"version": "0.8.0"}}, {"foo": 1}, {"agent_tokens": [{"id": 1}]}):
        with pytest.raises(backup.BackupFormatError, match="no supported table data"):
            backup.validate_backup_payload(payload, require_table=True)


def test_unsupported_keys_stay_filtered_by_the_internal_import(backup_db):  # noqa: F811
    # The internal import keeps its old behaviour: agent_tokens is ignored, not an error
    assert backup._write_db(backup_db, {"agent_tokens": [{"device_id": 1, "token": "x"}]}) == {}
    assert _query(backup_db, "SELECT token FROM agent_tokens") == [("live-agent-token",)]


# --- import: an empty list empties on purpose, a missing key keeps the data ----------------------

def test_an_empty_list_empties_its_table_on_purpose(backup_db):  # noqa: F811
    imported = backup._write_db(backup_db, {"devices": [], "device_groups": []})

    assert imported == {"devices": 0, "device_groups": 0}
    assert _query(backup_db, "SELECT COUNT(*) FROM devices") == [(0,)]
    assert _query(backup_db, "SELECT COUNT(*) FROM device_groups") == [(0,)]


def test_a_missing_key_keeps_the_table(backup_db):  # noqa: F811
    before = _snapshot(backup_db)

    imported = backup._write_db(backup_db, {"metadata": {"version": "0.1.0"}, "services": []})

    assert imported == {"services": 0}
    after = _snapshot(backup_db)
    assert after["devices"] == before["devices"] and after["groups"] == before["groups"]


# --- import: every wrong shape is refused before any change -------------------------------------

@pytest.mark.parametrize("value", [None, {}, False, 0, ""], ids=_ids([None, {}, False, 0, ""]))
def test_the_internal_import_does_not_read_a_falsy_non_list_as_an_empty_table(backup_db, value):  # noqa: F811
    # Reproduced bug: {"devices": {}} / false / 0 / "" passed the check and ran DELETE FROM devices
    before = _snapshot(backup_db)

    with pytest.raises(backup.BackupFormatError):
        backup._write_db(backup_db, {"devices": value})

    assert _snapshot(backup_db) == before


@pytest.mark.parametrize("value", NOT_A_LIST, ids=_ids(NOT_A_LIST))
def test_a_wrong_table_later_in_the_file_leaves_the_earlier_tables_unchanged(backup_db, value):  # noqa: F811
    before = _snapshot(backup_db)
    payload = {
        "device_groups": [{"id": 10, "name": "Replaced"}],
        "settings": [{"key": "scan_interval", "value": "99", "category": "scan"}],
        "devices": [{"id": 2, "ip": "10.0.0.2", "display_name": "a"}],
        "services": value,
    }

    with pytest.raises(backup.BackupFormatError):
        backup._write_db(backup_db, payload)

    assert _snapshot(backup_db) == before
    # nothing stays locked or half open
    backup._write_db(backup_db, {"settings": [{"key": "scan_interval", "value": "7", "category": "scan"}]})
    assert _settings(backup_db)["scan_interval"] == "7"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", NOT_A_LIST, ids=_ids(NOT_A_LIST))
async def test_the_import_endpoint_refuses_every_wrong_shape_with_400_and_changes_nothing(
    client, admin_token, import_endpoint_db, value,  # noqa: F811
):
    before = _snapshot(import_endpoint_db)
    payload = json.dumps({"device_groups": [{"id": 10, "name": "Replaced"}], "devices": value}).encode()

    response = await _post_backup(client, admin_token, payload)

    assert response.status_code == 400
    assert "'devices' must be a list of rows" in response.json()["detail"]
    assert _snapshot(import_endpoint_db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        (b"[]", "expected a JSON object"),
        (b'"x"', "expected a JSON object"),
        (b"null", "expected a JSON object"),
        (b"{}", "no supported table data"),
        (b'{"foo": 1}', "no supported table data"),
        (b'{"metadata": {"version": "0.8.0"}}', "no supported table data"),
        (b'{"metadata": "x", "devices": []}', "'metadata' must be an object"),
        (b'{"metadata": null, "devices": []}', "'metadata' must be an object"),
    ],
)
async def test_the_import_endpoint_refuses_files_that_are_no_backup(client, admin_token, import_endpoint_db, payload, detail):  # noqa: F811
    before = _snapshot(import_endpoint_db)

    response = await _post_backup(client, admin_token, payload)

    assert response.status_code == 400
    assert detail in response.json()["detail"]
    assert _snapshot(import_endpoint_db) == before


@pytest.mark.asyncio
async def test_the_import_endpoint_accepts_unknown_keys_next_to_supported_tables(client, admin_token, import_endpoint_db):  # noqa: F811
    payload = json.dumps({"from_a_later_version": [1, 2], "settings": [{"key": "scan_interval", "value": "12"}]}).encode()

    response = await _post_backup(client, admin_token, payload)

    assert response.status_code == 200
    assert _settings(import_endpoint_db)["scan_interval"] == "12"


@pytest.mark.asyncio
async def test_a_format_error_reaching_the_write_is_a_400_and_audited(client, admin_token, import_endpoint_db, db, monkeypatch):  # noqa: F811
    # Defense in depth: even if the upload check is bypassed, the import itself refuses and rolls back
    monkeypatch.setattr(backup, "_validate_backup_shape", lambda data: None)
    before = _snapshot(import_endpoint_db)

    response = await _post_backup(client, admin_token, json.dumps({"devices": False}).encode())

    assert response.status_code == 400
    assert "'devices' must be a list of rows" in response.json()["detail"]
    assert _snapshot(import_endpoint_db) == before
    events = (await db.execute(select(AuditEvent).where(AuditEvent.action == "backup.import"))).scalars().all()
    assert [(e.result, e.detail) for e in events] == [("failed", "invalid format")]


# --- setup restore: the same validation, with the setup gate open -------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, {}, False, 0, "", [1]], ids=_ids([None, {}, False, 0, "", [1]]))
async def test_setup_restore_and_import_refuse_a_wrong_shape_alike(client, admin_token, import_endpoint_db, db, value):  # noqa: F811
    body = json.dumps({"devices": value}).encode()
    files = {"file": ("backup.json", body, "application/json")}

    imported = await _post_backup(client, admin_token, body)
    # the import above needed the login; the wizard only works while setup.complete is missing
    await db.execute(delete(Setting))
    await db.commit()
    restored = await client.post("/api/setup/restore", files=files)

    assert imported.status_code == restored.status_code == 400
    assert imported.json()["detail"] == restored.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("value", NOT_A_LIST, ids=_ids(NOT_A_LIST))
async def test_setup_restore_refuses_every_wrong_shape_and_changes_nothing(client, fresh_instance_db, value):  # noqa: F811
    before = _snapshot(fresh_instance_db)
    payload = json.dumps({"device_groups": [{"id": 10, "name": "Replaced"}], "devices": value}).encode()

    response = await client.post("/api/setup/restore", files={"file": ("backup.json", payload, "application/json")})

    assert response.status_code == 400, response.text  # not 403: the setup gate is open here
    assert "'devices' must be a list of rows" in response.json()["detail"]
    assert _snapshot(fresh_instance_db) == before


@pytest.mark.asyncio
async def test_setup_restore_with_the_gate_open_still_restores_a_valid_backup(client, fresh_instance_db):  # noqa: F811
    # Control for the refusals above: the same endpoint and state take a valid file
    payload = json.dumps({"devices": [{"id": 7, "ip": "10.0.0.7", "display_name": "nas"}], "device_groups": []}).encode()

    response = await client.post("/api/setup/restore", files={"file": ("backup.json", payload, "application/json")})

    assert response.status_code == 200, response.text
    assert _query(fresh_instance_db, "SELECT display_name FROM devices") == [("nas",)]
    assert _query(fresh_instance_db, "SELECT COUNT(*) FROM device_groups") == [(0,)]


@pytest.mark.asyncio
async def test_setup_restore_refuses_a_file_without_supported_tables(client, fresh_instance_db):  # noqa: F811
    before = _snapshot(fresh_instance_db)

    response = await client.post("/api/setup/restore", files={"file": ("backup.json", b"{}", "application/json")})

    assert response.status_code == 400 and "no supported table data" in response.json()["detail"]
    assert _snapshot(fresh_instance_db) == before


# --- export: complete or visibly failed -----------------------------------------------------------

class _TrackedCursor:
    def __init__(self, real, fail_on=None, after_first_select=None):
        self._real, self._fail_on, self._after = real, fail_on, after_first_select

    def execute(self, sql, *args):
        if self._fail_on and self._fail_on in sql:
            raise sqlite3.OperationalError("database is locked")
        result = self._real.execute(sql, *args)
        if self._after and sql.startswith("SELECT"):
            hook, self._after = self._after, None
            hook()
        return result

    def __getattr__(self, name):
        return getattr(self._real, name)


class _TrackedConnection:
    """A sqlite3 connection that records being closed and can fail one table's SELECT."""

    def __init__(self, real, fail_on=None, after_first_select=None):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_fail_on", fail_on)
        object.__setattr__(self, "_after", after_first_select)
        object.__setattr__(self, "closed", False)

    def cursor(self):
        return _TrackedCursor(self._real.cursor(), self._fail_on, self._after)

    def close(self):
        object.__setattr__(self, "closed", True)
        self._real.close()

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        setattr(self._real, name, value)


@pytest.fixture
def tracked(monkeypatch):
    """Patch the export's connection; returns a list that receives every connection it opens."""
    opened: list[_TrackedConnection] = []

    def install(**options):
        real_open = backup._open_sqlite_connection

        def opener(path, isolation_level=""):
            conn = _TrackedConnection(real_open(path, isolation_level), **options)
            opened.append(conn)
            return conn

        monkeypatch.setattr(backup, "_open_sqlite_connection", opener)
        return opened

    return install


@pytest.mark.asyncio
async def test_a_complete_export_closes_its_connection(client, admin_token, import_endpoint_db, tracked):  # noqa: F811
    opened = tracked()

    response = await client.get("/api/backup/export", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 200
    assert "content-disposition" in response.headers
    assert set(backup.ALLOWED_TABLE_MAP) <= set(response.json())
    assert [c.closed for c in opened] == [True]


@pytest.mark.asyncio
async def test_a_database_error_gives_no_backup_file_and_closes_the_connection(
    client, admin_token, import_endpoint_db, db, tracked, caplog,  # noqa: F811
):
    opened = tracked(fail_on="FROM subnets")

    response = await client.get("/api/backup/export", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 500
    assert "content-disposition" not in response.headers
    body = response.json()
    assert set(body) == {"detail"}  # no table data, no half backup
    assert "locked" not in body["detail"] and "subnets" not in body["detail"]  # no internals
    assert [c.closed for c in opened] == [True]
    assert "database is locked" in caplog.text  # the cause stays in the server log
    events = (await db.execute(select(AuditEvent).where(AuditEvent.action == "backup.export"))).scalars().all()
    assert [(e.result, e.detail) for e in events] == [("failed", "table subnets could not be read")]


@pytest.mark.asyncio
async def test_a_failed_export_is_not_audited_as_successful(client, admin_token, import_endpoint_db, db):  # noqa: F811
    execute = sqlite3.connect(import_endpoint_db)
    execute.execute("DROP TABLE rack_ports")
    execute.commit()
    execute.close()

    response = await client.get("/api/backup/export", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 500
    events = (await db.execute(select(AuditEvent).where(AuditEvent.action == "backup.export"))).scalars().all()
    assert [e.result for e in events] == ["failed"]


@pytest.mark.asyncio
async def test_a_successful_export_is_audited_once(client, admin_token, import_endpoint_db, db):  # noqa: F811
    response = await client.get("/api/backup/export", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 200
    events = (await db.execute(select(AuditEvent).where(AuditEvent.action == "backup.export"))).scalars().all()
    assert [(e.result, e.detail) for e in events] == [("ok", "1 devices")]


@pytest.mark.asyncio
async def test_the_export_reads_every_table_from_one_snapshot(client, admin_token, import_endpoint_db, tracked):  # noqa: F811
    """A write committed between two SELECTs must not show up in a later table of the same export."""
    seed = sqlite3.connect(import_endpoint_db)
    seed.execute("PRAGMA journal_mode=WAL")  # the app's mode: readers keep their snapshot, writers are not blocked
    seed.close()

    def write_from_another_connection():
        other = sqlite3.connect(import_endpoint_db, timeout=1)
        try:
            # A copy of device 1 under a new id and address: no NOT NULL column to list by hand
            other.executescript(
                "CREATE TEMP TABLE late AS SELECT * FROM devices WHERE id = 1;"
                "UPDATE late SET id = 2, ip = '10.0.0.2', display_name = 'late arrival';"
                "INSERT INTO devices SELECT * FROM late;"
            )
            other.commit()
        finally:
            other.close()

    opened = tracked(after_first_select=write_from_another_connection)

    response = await client.get("/api/backup/export", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 200
    assert [d["ip"] for d in response.json()["devices"]] == ["10.0.0.1"]  # the first table's state, not a later one
    assert [c.closed for c in opened] == [True]
    # the write itself was not blocked: it is in the database afterwards
    assert _query(import_endpoint_db, "SELECT COUNT(*) FROM devices") == [(2,)]
