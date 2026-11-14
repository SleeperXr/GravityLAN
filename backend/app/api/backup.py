import asyncio
import importlib
import json
import sqlite3
import os
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.config import settings
from app.database.migrations import unique_column_sets

from app.api.auth import get_current_admin
from app.schemas.device import is_safe_url_template
from app.services.audit import record as audit
from app.services.stepup import require_step_up

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

# Rack cabling came into backups after 0.6.0: a backup that has these keys is complete for them, so an
# empty list empties the table. Older backups leave them out and keep what the instance has.
REPLACE_WHEN_EMPTY = frozenset({"rack_items", "rack_ports", "rack_cables"})

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
)


def invalidate_all_runtime_caches() -> None:
    """Clear all in-memory API caches after a database restore; one failure does not stop the others."""
    for module, name in _RUNTIME_CACHES:
        try:
            getattr(importlib.import_module(module), name).clear()
        except Exception as e:
            logger.warning("Could not clear %s: %s", name, e)


@router.get("/export", dependencies=[Depends(get_current_admin), Depends(require_step_up("instance"))])
async def export_backup(request: Request):
    """Export the current database state as a JSON file."""
    db_path = settings.effective_database_url.replace("sqlite+aiosqlite:///", "")
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Database file not found")

    def _read_db() -> dict:
        conn = _open_sqlite_connection(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        data: dict = {
            "metadata": {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "version": settings.app_version,
                "source": "GravityLAN Dashboard",
            },
            "device_groups": [],
            "devices": [],
            "services": [],
            "discovered_hosts": [],
            "settings": [],
        }
        # The tables an import may restore; agent_tokens is excluded for security (Issue 13)
        for key, table in ALLOWED_TABLE_MAP.items():
            try:
                cursor.execute(f"SELECT * FROM {table}")
                rows = [dict(row) for row in cursor.fetchall()]
                if key == "settings":
                    # The instance's credentials stay out of the file; an import ignores them anyway
                    rows = [r for r in rows if r.get("key") not in PROTECTED_SETTING_KEYS]
                data[key] = rows
            except sqlite3.OperationalError as e:
                logger.warning(f"Backup: Table {table} skipped ({e})")
        conn.close()
        return data

    try:
        data = await asyncio.to_thread(_read_db)
        await audit(request, "backup.export", detail=f"{len(data.get('devices', []))} devices")
        filename = f"gravitylan_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        return JSONResponse(
            content=data,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error(f"Backup: Export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
DEVICE_BOUND_DELETE = ("agent_tokens", "device_interfaces", "device_history", "rack_ports")
DEVICE_BOUND_UNLINK = ("ssh_profiles", "ssh_history")


def _device_identities(cursor) -> dict[int, tuple[str, str]]:
    """Device id -> (MAC in lower case, IP) of the devices table."""
    cursor.execute("SELECT id, mac, ip FROM devices")
    return {row[0]: ((row[1] or "").strip().lower(), (row[2] or "").strip()) for row in cursor.fetchall()}


def _same_device(before: tuple[str, str], after: tuple[str, str]) -> bool:
    """Same device when the MACs match; the IP decides only if one side has no MAC."""
    if before[0] and after[0]:
        return before[0] == after[0]
    return before[1] == after[1]


def _existing_tables(cursor) -> set[str]:
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row[0] for row in cursor.fetchall()}


def _reassigned_ids(before: dict[int, tuple[str, str]], after: dict[int, tuple[str, str]]) -> list[int]:
    """Device ids of ``before`` that are gone or name another device in ``after``."""
    return sorted(
        device_id for device_id, identity in before.items()
        if device_id not in after or not _same_device(identity, after[device_id])
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
    columns = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    cursor.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [tuple(r.get(c) for c in columns) for r in rows],
    )


def _restorable_table(key: str, rows) -> str | None:
    """The table a backup key restores, or None when this key is to be skipped."""
    if key == "metadata" or (not rows and key not in REPLACE_WHEN_EMPTY):
        return None
    if key not in ALLOWED_TABLE_MAP:
        logger.warning(f"Backup: Skipping unauthorized table key '{key}'")
        return None
    return ALLOWED_TABLE_MAP[key]


def _import_tables(cursor, data: dict) -> tuple[dict[str, int], dict[str, int]]:
    """Replace each table the backup has. Returns (table -> rows imported, table -> duplicates dropped)."""
    imported: dict[str, int] = {}
    duplicates: dict[str, int] = {}
    for key, rows in data.items():
        table = _restorable_table(key, rows)
        if table is None:
            continue
        valid_rows = _clean_rows(cursor, table, rows) if rows else []
        if not valid_rows and key not in REPLACE_WHEN_EMPTY:
            continue
        valid_rows, dropped = _drop_duplicates(table, valid_rows)
        if dropped:
            duplicates[table] = dropped
            logger.warning("Backup: %d duplicate row(s) in %s skipped, the newest of each kept", dropped, table)

        _replace_table(cursor, table, valid_rows)
        imported[table] = len(valid_rows)
    return imported, duplicates


def _count_agent_tokens(cursor) -> int:
    cursor.execute("SELECT COUNT(*) FROM agent_tokens")
    return cursor.fetchone()[0]


def _apply_backup(cursor, data: dict, report: dict | None) -> dict[str, int]:
    """The import itself, inside the open transaction of :func:`_write_db`."""
    protected_before = _read_protected_settings(cursor)
    devices_before = _device_identities(cursor)
    tokens_before = _count_agent_tokens(cursor)

    imported, duplicates = _import_tables(cursor, data)

    if _read_protected_settings(cursor) != protected_before:
        raise RuntimeError("Backup import would change protected settings")

    reassigned = _detach_reassigned_devices(cursor, devices_before, frozenset(imported))
    _drop_orphaned_rack_rows(cursor)
    _drop_dangling_links(cursor)
    if report is not None:
        report["agent_tokens_revoked"] = tokens_before - _count_agent_tokens(cursor)
        report["reassigned_device_ids"] = reassigned
        report["duplicates_dropped"] = duplicates
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


def _validate_backup_shape(data) -> None:
    """Reject payloads that are not {table_key: [row, ...]} before touching the database."""
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Invalid backup file: expected a JSON object")
    for key, rows in data.items():
        if key == "metadata" or key not in ALLOWED_TABLE_MAP or not rows:
            continue
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise HTTPException(status_code=400, detail=f"Invalid backup file: '{key}' must be a list of rows")


@router.post("/import", dependencies=[Depends(get_current_admin), Depends(require_step_up("instance"))])
async def import_backup(request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Import a JSON backup file into the database."""
    return await restore_upload(request, file, db)


async def _read_backup_upload(file: UploadFile) -> dict:
    """The parsed backup of an upload; HTTP 400/413 when it is no usable backup file."""
    if not file.filename.endswith(".json"):
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


def _import_message(revoked: int, skipped: int) -> str:
    message = "Backup successfully imported"
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


async def restore_upload(request: Request, file: UploadFile, db: AsyncSession, actor: str | None = None) -> dict:
    """Check, write and clean up after an uploaded backup; used by the import and the setup wizard."""
    data = await _read_backup_upload(file)

    db_path = settings.effective_database_url.replace("sqlite+aiosqlite:///", "")
    report: dict = {}
    try:
        imported = await asyncio.to_thread(_write_db, db_path, data, report)
    except Exception as e:
        logger.error(f"Backup: Import failed, all changes rolled back: {e}")
        await audit(request, "backup.import", "failed", detail="rolled back", actor=actor)
        raise HTTPException(status_code=500, detail=f"Backup import failed, no changes were made: {e}")

    for table, count in imported.items():
        logger.info(f"Backup: Imported {count} rows into {table}")
    duplicates = report.get("duplicates_dropped", {})
    skipped = sum(duplicates.values())
    await audit(request, "backup.import", detail=_import_audit_detail(imported, skipped), actor=actor)

    reassigned = report.get("reassigned_device_ids", [])
    revoked = report.get("agent_tokens_revoked", 0)
    if reassigned:
        await _retire_reassigned_devices(db, reassigned, revoked)

    invalidate_all_runtime_caches()

    return {
        "status": "ok",
        "message": _import_message(revoked, skipped),
        "agent_tokens_revoked": revoked,
        "reassigned_devices": len(reassigned),
        "devices": imported.get("devices", 0),
        "duplicates_dropped": duplicates,
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
