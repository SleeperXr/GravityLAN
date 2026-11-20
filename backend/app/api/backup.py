import asyncio
from contextlib import asynccontextmanager
import importlib
import json
import sqlite3
import os
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.policy import policy, NO_API_TOKEN
from app.database import get_db
from app.config import settings
from app.database.migrations import unique_column_sets

from app.schemas.device import is_safe_url_template
from app.services.audit import record as audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backup", tags=["backup"])

MAX_BACKUP_BYTES = 10 * 1024 * 1024

# Backup key -> table a backup may restore. agent_tokens is left out, matching the
# export (Issue 13): restoring old agent credentials would revive revoked agents.
ALLOWED_TABLE_MAP = {
    "device_groups": "device_groups",
    "devices": "devices",
    "device_interfaces": "device_interfaces",
    "services": "services",
    "discovered_hosts": "discovered_hosts",
    "settings": "app_settings",
    "agent_configs": "agent_configs",
    "subnets": "subnets",
    "topology_links": "topology_links",
    "racks": "racks",
    "rack_items": "rack_items",
    "rack_ports": "rack_ports",
    "rack_cables": "rack_cables",
}

# A key the backup has is complete for its table: an empty list empties it (only rack cabling did
# that until 0.8.0; restoring an emptied device list kept the old devices). A key it leaves out,
# as older backups do for tables that came later, keeps what the instance has.

# Credentials and setup state of the running instance. An import never deletes or
# replaces them: a backup from another instance (or a tampered one) would otherwise
# lock the admin out, hand over access, or reopen the unauthenticated setup wizard.
PROTECTED_SETTING_KEYS = ("api.master_token", "api.admin_password", "setup.complete")


def _open_sqlite_connection(db_path: str, isolation_level: str | None = "") -> sqlite3.Connection:
    """Open a sqlite3 connection configured with busy_timeout=15000."""
    conn = sqlite3.connect(db_path, timeout=15.0, isolation_level=isolation_level)
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


# Module -> dict-like cache that describes the database. Looked up on use: these API modules import this one.
_RUNTIME_CACHES = (
    ("app.api.devices", "dashboard_cache"),
    ("app.api.topology", "topology_cache"),
    ("app.api.discovery", "discovery_cache"),
    ("app.api.agent", "_latest_metrics"),
    ("app.api.auth", "_setting_cache"),
    # agent.allow_auto_adoption: a restored "off" must not stay "on" for the cache's five minutes
    ("app.services.agent_telemetry", "_setting_cache"),
)


def invalidate_all_runtime_caches() -> None:
    """Clear all in-memory API caches after a database restore; one failure does not stop the others."""
    for module, name in _RUNTIME_CACHES:
        try:
            getattr(importlib.import_module(module), name).clear()
        except Exception as e:
            logger.warning("Could not clear %s: %s", name, e)


SQLITE_ONLY_DETAIL = (
    "Backup and restore only work with the built-in SQLite database. "
    "With GRAVITYLAN_DATABASE_URL, back up that database with its own tools."
)


def _sqlite_db_path() -> str:
    """Path of the SQLite inventory file; 400 when an external database is configured."""
    if not settings.uses_sqlite:
        raise HTTPException(status_code=400, detail=SQLITE_ONLY_DETAIL)
    return settings.effective_database_url.replace("sqlite+aiosqlite:///", "")


class BackupExportError(RuntimeError):
    """A table of the backup could not be read; the export has to fail rather than come out partial."""

    def __init__(self, table: str):
        super().__init__(f"table {table} could not be read")
        self.table = table


EXPORT_FAILED_DETAIL = (
    "Backup export failed: the database could not be read completely, so no backup file was created. "
    "Details are in the server log."
)


def _export_snapshot(db_path: str) -> dict:
    """Every backup table, read inside one read transaction.

    A deferred ``BEGIN`` pins one snapshot at the first SELECT: in WAL mode (the app's mode) all tables
    come from the same database state while writers are not blocked; without it each SELECT would see
    whatever was committed in between. A table that cannot be read (missing, locked, corrupt) raises
    :class:`BackupExportError` instead of being left out: an incomplete file must not pass as a backup.
    """
    conn = None
    table = "(transaction)"
    try:
        conn = _open_sqlite_connection(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        data: dict = {
            "metadata": {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "version": settings.app_version,
                "source": "GravityLAN Dashboard",
            },
        }
        # The tables an import may restore; agent_tokens is excluded for security (Issue 13)
        for key, table in ALLOWED_TABLE_MAP.items():
            cursor.execute(f"SELECT * FROM {table}")
            rows = [dict(row) for row in cursor.fetchall()]
            if key == "settings":
                # The instance's credentials stay out of the file; an import ignores them anyway
                rows = [r for r in rows if r.get("key") not in PROTECTED_SETTING_KEYS]
            data[key] = rows
        return data
    except sqlite3.Error as exc:
        raise BackupExportError(table) from exc
    finally:
        if conn is not None:
            conn.close()


@router.get("/export", dependencies=[policy(callers=NO_API_TOKEN, step_up="instance")])
async def export_backup(request: Request):
    """Export the current database state as a JSON file; complete, or a visible failure (HTTP 500)."""
    db_path = _sqlite_db_path()
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Database file not found")

    try:
        data = await asyncio.to_thread(_export_snapshot, db_path)
        filename = f"gravitylan_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        response = JSONResponse(
            content=data,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as exc:
        # The cause stays in the log; the client only learns that no backup was made
        logger.error("Backup: export failed, no file created: %s (%s)", exc, exc.__cause__ or "no further cause")
        reason = str(exc) if isinstance(exc, BackupExportError) else "unexpected error"
        await audit(request, "backup.export", "failed", detail=reason)
        raise HTTPException(status_code=500, detail=EXPORT_FAILED_DETAIL) from exc
    await audit(request, "backup.export", detail=f"{len(data.get('devices', []))} devices")
    return response


def _read_protected_settings(cursor) -> dict[str, str]:
    """Current values of the protected app_settings keys."""
    placeholders = ", ".join("?" * len(PROTECTED_SETTING_KEYS))
    cursor.execute(f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})", PROTECTED_SETTING_KEYS)
    return dict(cursor.fetchall())


# Columns without an SQL default whose model default is not the type's zero value
_MODEL_DEFAULTS: dict[tuple[str, str], int] = {
    ("devices", "alert_offline"): 1,
    ("devices", "is_online"): 1,
    ("services", "is_up"): 1,
    ("services", "is_auto_detected"): 1,
    ("discovered_hosts", "is_online"): 1,
    ("device_interfaces", "is_online"): 1,
    ("agent_configs", "enable_temp"): 1,
    ("agent_configs", "enable_patch_check"): 1,
    ("agent_tokens", "is_active"): 1,
    ("agent_configs", "interval"): 30,
    ("agent_configs", "version"): 1,
}


def _is_numeric_type(col_type: str) -> bool:
    return any(t in col_type.upper() for t in ("INT", "BOOLEAN"))


def _from_sql_default(sql_default, col_type: str, now_str: str):
    """The value a column's SQL default stands for (CURRENT_TIMESTAMP, TRUE/FALSE, numbers, text)."""
    cleaned = str(sql_default).strip().strip("'\"")
    if cleaned.upper() in ("CURRENT_TIMESTAMP", "NOW()"):
        return now_str
    if _is_numeric_type(col_type):
        if cleaned.upper() in ("TRUE", "FALSE"):
            return 1 if cleaned.upper() == "TRUE" else 0
        try:
            return int(cleaned)
        except ValueError:
            pass
    return cleaned


def _default_for_missing_col(table: str, col: str, info: dict, now_str: str):
    """Fallback value for a NOT NULL column missing from an older backup."""
    if info.get("default") is not None:
        return _from_sql_default(info["default"], info["type"], now_str)
    if (table, col) in _MODEL_DEFAULTS:
        return _MODEL_DEFAULTS[(table, col)]
    if any(t in info["type"].upper() for t in ("DATETIME", "TIMESTAMP")):
        return now_str
    return 0 if _is_numeric_type(info["type"]) else ""


def _clean_rows(cursor, table: str, rows: list[dict]) -> list[dict]:
    """Keep only known columns and fill NOT NULL columns the backup left empty."""
    cursor.execute(f"PRAGMA table_info({table})")
    table_info = {
        col[1]: {"notnull": col[3], "default": col[4], "type": col[2]}
        for col in cursor.fetchall()
    }
    if not table_info:
        logger.error(f"Backup: Table {table} not found in DB")
        return []

    if table == "app_settings":
        # Protected keys stay as they are; ids are reassigned so restored rows
        # cannot collide with the protected rows that remain in the table.
        rows = [r for r in rows if r.get("key") not in PROTECTED_SETTING_KEYS]
        table_info.pop("id", None)

    now_str = datetime.now(timezone.utc).isoformat().replace("T", " ")
    return [_clean_row(table, row, table_info, now_str) for row in rows]


def _setting_row_valid(row: dict) -> bool:
    """A settings row passes the check POST /api/settings applies to the same key (app.api.settings)."""
    from app.api.settings import _VALIDATORS

    validator = _VALIDATORS.get(row.get("key"))
    value = row.get("value")
    if validator is None or value in (None, ""):
        return True
    try:
        validator(str(value))
    except HTTPException:
        return False
    return True


def _subnet_row_checked(row: dict) -> dict | None:
    """A subnets row normalized like one created on the Network page (schemas.network), or None when invalid."""
    from pydantic import ValidationError

    from app.schemas.network import SubnetCreate

    fields = {k: row[k] for k in ("cidr", "name", "dns_server", "gateway_ip", "vlan_id", "is_enabled") if k in row}
    if fields.get("is_enabled") is None:
        fields.pop("is_enabled", None)
    if fields.get("name") is None:
        fields.pop("name", None)
    try:
        subnet = SubnetCreate(**fields)
    except (ValidationError, TypeError, ValueError):
        return None
    checked = dict(row)
    checked.update(cidr=subnet.cidr, name=subnet.name, dns_server=subnet.dns_server, gateway_ip=subnet.gateway_ip)
    return checked


def _validated_rows(table: str, rows: list[dict]) -> tuple[list[dict], int]:
    """The rows of a settings or subnets table that pass the app's own input checks; (rows, number dropped).

    A backup is a file anyone could have edited. Settings reach the install script (server.url)
    and nmap (dns.server), subnets reach nmap and the DNS resolver, so they must pass the same
    checks as when they are typed into GravityUI. Rows that do not are left out and reported.
    """
    if table == "app_settings":
        kept = [row for row in rows if _setting_row_valid(row)]
        for row in rows:
            if row not in kept:
                logger.warning("Backup: setting %r left out, its value does not pass the settings check", row.get("key"))
        return kept, len(rows) - len(kept)
    if table == "subnets":
        kept = []
        for row in rows:
            checked = _subnet_row_checked(row)
            if checked is None:
                logger.warning("Backup: subnet %r left out, it is not a valid scan subnet", str(row.get("cidr"))[:60])
            else:
                kept.append(checked)
        return kept, len(rows) - len(kept)
    return rows, 0


def _known_columns(row: dict, table_info: dict) -> dict:
    """The row without unknown columns and without empty values for NOT NULL columns."""
    return {
        col: val
        for col, val in row.items()
        if col in table_info and not (val is None and table_info[col]["notnull"])
    }


def _fill_required_columns(clean_row: dict, table: str, table_info: dict, now_str: str) -> None:
    for col, info in table_info.items():
        if info["notnull"] and clean_row.get(col) is None:
            clean_row[col] = _default_for_missing_col(table, col, info, now_str)


def _drop_unsafe_url_template(service: dict) -> None:
    """A tampered backup must not smuggle javascript: links into the dashboard (#42)."""
    if not is_safe_url_template(service.get("url_template") or ""):
        logger.warning(f"Backup: Dropping unsafe url_template of service {service.get('name')!r}")
        service["url_template"] = ""


def _clean_row(table: str, row: dict, table_info: dict, now_str: str) -> dict:
    """Known columns only; NOT NULL columns the backup left out or empty get their default."""
    clean_row = _known_columns(row, table_info)
    _fill_required_columns(clean_row, table, table_info, now_str)
    if table == "services":
        _drop_unsafe_url_template(clean_row)
    return clean_row


# Rows outside the backup that belong to one device (#47): when a device id names another
# device after the import, these are deleted, the saved SSH connections are only unbound.
DEVICE_BOUND_DELETE = ("agent_tokens", "device_interfaces", "device_history", "rack_ports", "device_mac_observations")
DEVICE_BOUND_UNLINK = ("ssh_profiles", "ssh_history")


def _device_identities(cursor) -> dict[int, tuple[str, str]]:
    """Device id -> (MAC in lower case, IP) of the devices table."""
    cursor.execute("SELECT id, mac, ip FROM devices")
    return {row[0]: ((row[1] or "").strip().lower(), (row[2] or "").strip()) for row in cursor.fetchall()}


def _same_device(before: tuple[str, str], after: tuple[str, str], shared_macs: frozenset[str] = frozenset()) -> bool:
    """Same device when the MACs match; the IP decides only if one side has no MAC.

    A MAC that several devices carry (ipvlan containers share their host's) cannot tell them
    apart: a backup that swapped two such containers' ids would keep each one's agent token,
    history and MAC sightings on the other. For those the IP has to match as well.
    """
    if before[0] and after[0]:
        if before[0] != after[0]:
            return False
        return before[0] not in shared_macs or before[1] == after[1]
    return before[1] == after[1]


def _shared_macs(*identities: dict[int, tuple[str, str]]) -> frozenset[str]:
    """MACs that more than one device carries on either side."""
    shared: set[str] = set()
    for side in identities:
        seen: set[str] = set()
        for mac, _ in side.values():
            if mac and mac in seen:
                shared.add(mac)
            seen.add(mac)
    return frozenset(shared)


def _existing_tables(cursor) -> set[str]:
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row[0] for row in cursor.fetchall()}


def _reassigned_ids(before: dict[int, tuple[str, str]], after: dict[int, tuple[str, str]]) -> list[int]:
    """Device ids of ``before`` that are gone or name another device in ``after``."""
    shared = _shared_macs(before, after)
    return sorted(
        device_id for device_id, identity in before.items()
        if device_id not in after or not _same_device(identity, after[device_id], shared)
    )


def _delete_device_bound_rows(cursor, deletable: set[str], reassigned: list[int]) -> None:
    placeholders = ", ".join("?" * len(reassigned))
    for table in DEVICE_BOUND_DELETE:
        if table in deletable:
            cursor.execute(f"DELETE FROM {table} WHERE device_id IN ({placeholders})", reassigned)


def _unlink_device_bound_rows(
    cursor, existing: set[str], reassigned: list[int], before: dict[int, tuple[str, str]]
) -> None:
    for table in DEVICE_BOUND_UNLINK:
        if table in existing:
            # A connection bound to a device may have no host of its own: keep the old
            # device's address as its target, or it would point nowhere after the unlink
            cursor.executemany(
                f"UPDATE {table} SET host = COALESCE(NULLIF(host, ''), ?), device_id = NULL WHERE device_id = ?",
                [(before[device_id][1] or None, device_id) for device_id in reassigned],
            )


def _detach_reassigned_devices(
    cursor, before: dict[int, tuple[str, str]], restored: frozenset[str] = frozenset()
) -> list[int]:
    """Drop what the old devices left behind under ids that now name another (or no) device.

    Agent tokens, interfaces and history are deleted, so an agent of the old device can no
    longer report as the new one; it has to be enrolled again. Saved SSH connections and
    their history stay, but lose the device binding. Tables in ``restored`` came from the
    backup itself and already belong to the new devices, so they are left alone.
    Returns the affected device ids.
    """
    reassigned = _reassigned_ids(before, _device_identities(cursor))
    if not reassigned:
        return []
    existing = _existing_tables(cursor)
    _delete_device_bound_rows(cursor, existing - restored, reassigned)
    _unlink_device_bound_rows(cursor, existing, reassigned, before)
    return reassigned


def _drop_orphaned_rack_rows(cursor) -> None:
    """Do what ON DELETE CASCADE would have done: the import runs with foreign keys off.

    Rack items on a rack the backup no longer has, ports of a device or item that is gone, and
    cables on a port that is gone are deleted, so no cable ends up in another rack.
    """
    if not {"racks", "rack_items", "rack_ports", "rack_cables"} <= _existing_tables(cursor):
        return
    cursor.execute("DELETE FROM rack_items WHERE rack_id NOT IN (SELECT id FROM racks)")
    cursor.execute(
        "DELETE FROM rack_ports WHERE (device_id IS NOT NULL AND device_id NOT IN (SELECT id FROM devices))"
        " OR (rack_item_id IS NOT NULL AND rack_item_id NOT IN (SELECT id FROM rack_items))"
    )
    cursor.execute(
        "DELETE FROM rack_cables WHERE a_port_id NOT IN (SELECT id FROM rack_ports)"
        " OR b_port_id NOT IN (SELECT id FROM rack_ports)"
    )


def _drop_dangling_links(cursor) -> None:
    """Orbit links whose device the backup no longer has (foreign keys are off during the import)."""
    cursor.execute(
        "DELETE FROM topology_links WHERE source_id NOT IN (SELECT id FROM devices)"
        " OR target_id NOT IN (SELECT id FROM devices)"
    )


def _is_duplicate(keys: list[tuple], seen: list[set]) -> bool:
    return any(None not in key and key in taken for key, taken in zip(keys, seen))


def _remember_keys(keys: list[tuple], seen: list[set]) -> None:
    for key, taken in zip(keys, seen):
        if None not in key:
            taken.add(key)


def _row_id(row: dict) -> int:
    return row.get("id") or 0


def _drop_duplicates(table: str, rows: list[dict]) -> tuple[list[dict], int]:
    """Keep one row per unique key, the newest (highest id).

    Databases from before a unique constraint existed can hold duplicates, e.g. the same link twice;
    create_all never adds a constraint to an existing table, so only a fresh instance refused them and
    the whole import failed. Rows with an empty key column are never duplicates (SQL ignores NULL).
    """
    key_sets = unique_column_sets(table)
    if not key_sets:
        return rows, 0
    seen: list[set] = [set() for _ in key_sets]
    kept = []
    for row in sorted(rows, key=_row_id, reverse=True):
        keys = [tuple(row.get(c) for c in cols) for cols in key_sets]
        if _is_duplicate(keys, seen):
            continue
        _remember_keys(keys, seen)
        kept.append(row)
    kept.sort(key=_row_id)
    return kept, len(rows) - len(kept)


def _replace_table(cursor, table: str, rows: list[dict]) -> None:
    """Delete the table's rows (protected settings stay) and insert ``rows``; the columns of the first row count."""
    if table == "app_settings":
        placeholders = ", ".join("?" * len(PROTECTED_SETTING_KEYS))
        cursor.execute(f"DELETE FROM app_settings WHERE key NOT IN ({placeholders})", PROTECTED_SETTING_KEYS)
    else:
        cursor.execute(f"DELETE FROM {table}")
    if not rows:
        return
    # Every column any row has: taking the first row's only dropped the values of columns it lacked
    columns = list(dict.fromkeys(col for row in rows for col in row))
    placeholders = ", ".join(["?"] * len(columns))
    cursor.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [tuple(r.get(c) for c in columns) for r in rows],
    )


def _restorable_table(key: str) -> str | None:
    """The table a backup key restores, or None when this key is to be skipped."""
    # A key the backup has replaces its table, also when its list is empty (the instance had none of
    # these: restoring it means none now); a key it leaves out (an older backup) keeps the table.
    # Only lists get here: validate_backup_payload refuses every other value of a table key.
    if key == "metadata":
        return None
    if key not in ALLOWED_TABLE_MAP:
        logger.warning(f"Backup: Skipping unauthorized table key '{key}'")
        return None
    return ALLOWED_TABLE_MAP[key]


def _import_tables(cursor, data: dict) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Replace each table the backup has.

    Returns (table -> rows imported, table -> duplicates dropped, table -> invalid rows dropped).
    Raises :class:`BackupFormatError` before the first table is touched when a table key is not a list
    of rows (an internal caller must not turn ``{}``, ``false`` or ``null`` into an emptied table).
    """
    validate_backup_payload(data)
    imported: dict[str, int] = {}
    duplicates: dict[str, int] = {}
    invalid: dict[str, int] = {}
    for key, rows in data.items():
        table = _restorable_table(key)
        if table is None:
            continue
        checked, rejected = _validated_rows(table, rows) if rows else ([], 0)
        if rejected:
            invalid[table] = rejected
        valid_rows = _clean_rows(cursor, table, checked) if checked else []
        if rows and not valid_rows:
            continue  # every row was dropped while cleaning: keep the table rather than empty it
        valid_rows, dropped = _drop_duplicates(table, valid_rows)
        if dropped:
            duplicates[table] = dropped
            logger.warning("Backup: %d duplicate row(s) in %s skipped, the newest of each kept", dropped, table)

        _replace_table(cursor, table, valid_rows)
        imported[table] = len(valid_rows)
    return imported, duplicates, invalid


def _count_agent_tokens(cursor) -> int:
    cursor.execute("SELECT COUNT(*) FROM agent_tokens")
    return cursor.fetchone()[0]


def _apply_backup(cursor, data: dict, report: dict | None) -> dict[str, int]:
    """The import itself, inside the open transaction of :func:`_write_db`."""
    protected_before = _read_protected_settings(cursor)
    devices_before = _device_identities(cursor)
    tokens_before = _count_agent_tokens(cursor)

    imported, duplicates, invalid = _import_tables(cursor, data)

    if _read_protected_settings(cursor) != protected_before:
        raise RuntimeError("Backup import would change protected settings")

    reassigned = _detach_reassigned_devices(cursor, devices_before, frozenset(imported))
    _drop_orphaned_rack_rows(cursor)
    _drop_dangling_links(cursor)
    if report is not None:
        report["agent_tokens_revoked"] = tokens_before - _count_agent_tokens(cursor)
        report["reassigned_device_ids"] = reassigned
        report["duplicates_dropped"] = duplicates
        report["invalid_dropped"] = invalid
    return imported


def _write_db(db_path: str, data: dict, report: dict | None = None) -> dict[str, int]:
    """Replace the allowed tables with the backup rows in a single transaction.

    Any error rolls everything back, so a failed import never leaves a
    half-deleted database behind. ``report`` receives ``agent_tokens_revoked``
    and ``reassigned_device_ids`` (see :func:`_detach_reassigned_devices`).
    """
    # isolation_level=None: no implicit transactions, BEGIN/COMMIT are explicit below
    conn = _open_sqlite_connection(db_path, isolation_level=None)
    cursor = conn.cursor()
    try:
        # Only takes effect outside a transaction, so it is set before BEGIN
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("BEGIN IMMEDIATE")
        imported = _apply_backup(cursor, data, report)
        conn.commit()
        return imported
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            conn.close()


class BackupFormatError(ValueError):
    """The payload is not a backup of the shape {table_key: [row, ...]}."""


def validate_backup_payload(data, *, require_table: bool = False) -> None:
    """Check a backup payload before any table is touched; raises :class:`BackupFormatError`.

    Shared by the upload check (HTTP 400, ``require_table=True``) and the import itself, so no caller
    can reach the tables with a wrong shape. For every supported table key the value must be a list of
    objects: ``[]`` is valid and empties the table on purpose; ``null``, ``{}``, ``false``, ``0``,
    ``""`` and the like are not (they used to pass as "empty" and wiped the table). A key the backup
    leaves out keeps its table; unknown keys are ignored. ``metadata`` may be missing, else an object.
    """
    if not isinstance(data, dict):
        raise BackupFormatError("Invalid backup file: expected a JSON object")
    if "metadata" in data and not isinstance(data["metadata"], dict):
        raise BackupFormatError("Invalid backup file: 'metadata' must be an object")
    present = [key for key in data if key in ALLOWED_TABLE_MAP]
    for key in present:
        rows = data[key]
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise BackupFormatError(f"Invalid backup file: '{key}' must be a list of rows")
    if require_table and not present:
        raise BackupFormatError("Invalid backup file: it contains no supported table data")


def _validate_backup_shape(data) -> None:
    """Reject uploads that are no usable backup (HTTP 400) before touching the database."""
    try:
        validate_backup_payload(data, require_table=True)
    except BackupFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import", dependencies=[policy(callers=NO_API_TOKEN, step_up="instance")])
async def import_backup(request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Import a JSON backup file into the database."""
    return await restore_upload(request, file, db)


async def _read_backup_upload(file: UploadFile) -> dict:
    """The parsed backup of an upload; HTTP 400/413 when it is no usable backup file."""
    if not (file.filename or "").lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are supported")

    # Issue 8: Read with size limit (10MB max) to prevent memory exhaustion DOS
    content = await file.read(size=MAX_BACKUP_BYTES)
    if len(content) >= MAX_BACKUP_BYTES:
        raise HTTPException(status_code=413, detail="Backup file too large (max 10MB)")

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid backup file: not valid JSON")
    _validate_backup_shape(data)
    return data


def _import_audit_detail(imported: dict[str, int], skipped: int) -> str:
    detail = f"{imported.get('devices', 0)} devices, {imported.get('app_settings', 0)} settings"
    return f"{detail}, {skipped} duplicates skipped" if skipped else detail


def _import_message(revoked: int, skipped: int, invalid: int = 0) -> str:
    message = "Backup successfully imported"
    if invalid:
        message += (
            f". {invalid} setting(s) or subnet(s) did not pass the input checks and were left out (see the log)"
        )
    if revoked:
        message += f". {revoked} agent(s) belonged to devices that are different now and must be enrolled again"
    if skipped:
        message += f". {skipped} duplicate entr{'y was' if skipped == 1 else 'ies were'} skipped, the newest of each kept"
    return message


async def _retire_reassigned_devices(db: AsyncSession, reassigned: list[int], revoked: int) -> None:
    """Remove what outlives the database import for device ids that now name other devices."""
    # Revoke first: the import is committed, and an old install code must not be redeemed
    # while the measurement data is still being deleted
    await _revoke_device_grants(reassigned)
    await _purge_telemetry(db, reassigned)
    logger.warning(
        "Backup: %d device id(s) now name other devices; removed their agent tokens (%d), interfaces and "
        "measurement data", len(reassigned), revoked,
    )


@asynccontextmanager
async def _scheduler_paused():
    """Stop the background scans and jobs while the tables are replaced, like the database reset.

    A scan that writes devices or subnets in the middle of the import would mix old and new
    rows or fail on rows that are gone. Restarted afterwards, also when the import fails.
    """
    from app.scanner.scheduler import scheduler

    was_running = scheduler.running
    if was_running:
        logger.info("Backup: pausing the scanner scheduler during the import")
        try:
            await asyncio.wait_for(scheduler.stop(), timeout=5.0)
        except (asyncio.TimeoutError, RuntimeError, OSError) as exc:
            logger.warning("Backup: scheduler stop failed or timed out: %s", exc)
    try:
        yield
    finally:
        if was_running:
            try:
                await scheduler.start()
            except (RuntimeError, OSError) as exc:
                logger.error("Backup: failed to restart the scheduler: %s", exc)


async def restore_upload(request: Request, file: UploadFile, db: AsyncSession, actor: str | None = None) -> dict:
    """Check, write and clean up after an uploaded backup; used by the import and the setup wizard."""
    db_path = _sqlite_db_path()
    data = await _read_backup_upload(file)
    async with _scheduler_paused():
        return await _restore(request, data, db, db_path, actor)


async def _restore(request: Request, data: dict, db: AsyncSession, db_path: str, actor: str | None) -> dict:
    report: dict = {}
    try:
        imported = await asyncio.to_thread(_write_db, db_path, data, report)
    except BackupFormatError as e:
        logger.error(f"Backup: Import refused, wrong format, nothing changed: {e}")
        await audit(request, "backup.import", "failed", detail="invalid format", actor=actor)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Backup: Import failed, all changes rolled back: {e}")
        await audit(request, "backup.import", "failed", detail="rolled back", actor=actor)
        raise HTTPException(status_code=500, detail=f"Backup import failed, no changes were made: {e}")

    for table, count in imported.items():
        logger.info(f"Backup: Imported {count} rows into {table}")
    duplicates = report.get("duplicates_dropped", {})
    skipped = sum(duplicates.values())
    invalid = report.get("invalid_dropped", {})
    await audit(request, "backup.import", detail=_import_audit_detail(imported, skipped), actor=actor)

    reassigned = report.get("reassigned_device_ids", [])
    revoked = report.get("agent_tokens_revoked", 0)
    if reassigned:
        await _retire_reassigned_devices(db, reassigned, revoked)

    invalidate_all_runtime_caches()

    return {
        "status": "ok",
        "message": _import_message(revoked, skipped, sum(invalid.values())),
        "agent_tokens_revoked": revoked,
        "reassigned_devices": len(reassigned),
        "devices": imported.get("devices", 0),
        "duplicates_dropped": duplicates,
        "invalid_dropped": invalid,
    }


async def _revoke_device_grants(device_ids: list[int]) -> None:
    """Revoke what still names the old devices outside the database (#47).

    Install codes and package update tickets carry a device id, and open metric streams
    of the dashboard follow one. After the import that id belongs to another device.
    """
    from app.api.agent_patches import _temp_patch_tokens
    from app.services.enrollment_service import enrollment_store
    from app.services.stream_revocation import close_metric_streams

    ids = set(device_ids)
    codes = enrollment_store.revoke_devices(ids)
    for token in [t for t, entry in _temp_patch_tokens.items() if entry["device_id"] in ids]:
        del _temp_patch_tokens[token]
    streams = await close_metric_streams(ids)
    logger.warning(
        "Backup: revoked %d install code(s) and closed %d metric stream(s) of re-assigned devices", codes, streams,
    )


async def _purge_telemetry(db: AsyncSession, device_ids: list[int]) -> None:
    """Delete measurement data (telemetry.db) recorded under device ids that changed meaning (#47)."""
    from sqlalchemy import delete
    from app.database import Base, TELEMETRY_SCHEMA

    for table in Base.metadata.sorted_tables:
        if table.schema != TELEMETRY_SCHEMA or "device_id" not in table.c:
            continue
        try:
            await db.execute(delete(table).where(table.c.device_id.in_(device_ids)))
        except Exception as e:
            logger.warning(f"Backup: Could not clean {table.fullname}: {e}")
    await db.commit()
