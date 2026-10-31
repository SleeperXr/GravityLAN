import asyncio
import json
import sqlite3
import os
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.config import settings

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


def invalidate_all_runtime_caches() -> None:
    """Clear all in-memory API caches after a database restore."""
    try:
        from app.api.devices import dashboard_cache
        dashboard_cache.clear()
    except Exception as e:
        logger.warning("Could not clear dashboard_cache: %s", e)

    try:
        from app.api.topology import topology_cache
        topology_cache.clear()
    except Exception as e:
        logger.warning("Could not clear topology_cache: %s", e)

    try:
        from app.api.discovery import discovery_cache
        discovery_cache.clear()
    except Exception as e:
        logger.warning("Could not clear discovery_cache: %s", e)

    try:
        from app.api.agent import _latest_metrics
        _latest_metrics.clear()
    except Exception as e:
        logger.warning("Could not clear _latest_metrics: %s", e)

    try:
        from app.api.auth import _setting_cache
        _setting_cache.clear()
    except Exception as e:
        logger.warning("Could not clear _setting_cache: %s", e)


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
                data[key] = [dict(row) for row in cursor.fetchall()]
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
    valid_rows = []
    for row in rows:
        clean_row = {
            col: val
            for col, val in row.items()
            if col in table_info and not (val is None and table_info[col]["notnull"])
        }
        for col, info in table_info.items():
            if info["notnull"] and (col not in clean_row or clean_row[col] is None):
                if any(t in info["type"].upper() for t in ("DATETIME", "TIMESTAMP")):
                    clean_row[col] = now_str
                elif any(t in info["type"].upper() for t in ("INT", "BOOLEAN")):
                    clean_row[col] = 0
                else:
                    clean_row[col] = ""
        if table == "services" and not is_safe_url_template(clean_row.get("url_template") or ""):
            # A tampered backup must not smuggle javascript: links into the dashboard (#42)
            logger.warning(f"Backup: Dropping unsafe url_template of service {clean_row.get('name')!r}")
            clean_row["url_template"] = ""
        valid_rows.append(clean_row)
    return valid_rows


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
    after = _device_identities(cursor)
    reassigned = sorted(
        device_id for device_id, identity in before.items()
        if device_id not in after or not _same_device(identity, after[device_id])
    )
    if not reassigned:
        return []
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    existing = {row[0] for row in cursor.fetchall()}
    placeholders = ", ".join("?" * len(reassigned))
    for table in DEVICE_BOUND_DELETE:
        if table in existing and table not in restored:
            cursor.execute(f"DELETE FROM {table} WHERE device_id IN ({placeholders})", reassigned)
    for table in DEVICE_BOUND_UNLINK:
        if table in existing:
            # A connection bound to a device may have no host of its own: keep the old
            # device's address as its target, or it would point nowhere after the unlink
            cursor.executemany(
                f"UPDATE {table} SET host = COALESCE(NULLIF(host, ''), ?), device_id = NULL WHERE device_id = ?",
                [(before[device_id][1] or None, device_id) for device_id in reassigned],
            )
    return reassigned


def _drop_orphaned_rack_rows(cursor) -> None:
    """Do what ON DELETE CASCADE would have done: the import runs with foreign keys off.

    Rack items on a rack the backup no longer has, ports of a device or item that is gone, and
    cables on a port that is gone are deleted, so no cable ends up in another rack.
    """
    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    if not {"racks", "rack_items", "rack_ports", "rack_cables"} <= {row[0] for row in cursor.fetchall()}:
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
        protected_before = _read_protected_settings(cursor)
        devices_before = _device_identities(cursor)
        cursor.execute("SELECT COUNT(*) FROM agent_tokens")
        tokens_before = cursor.fetchone()[0]
        imported: dict[str, int] = {}

        for key, rows in data.items():
            if key == "metadata" or (not rows and key not in REPLACE_WHEN_EMPTY):
                continue
            if key not in ALLOWED_TABLE_MAP:
                logger.warning(f"Backup: Skipping unauthorized table key '{key}'")
                continue

            table = ALLOWED_TABLE_MAP[key]
            valid_rows = _clean_rows(cursor, table, rows) if rows else []
            if not valid_rows and key not in REPLACE_WHEN_EMPTY:
                continue

            if table == "app_settings":
                placeholders = ", ".join("?" * len(PROTECTED_SETTING_KEYS))
                cursor.execute(f"DELETE FROM app_settings WHERE key NOT IN ({placeholders})", PROTECTED_SETTING_KEYS)
            else:
                cursor.execute(f"DELETE FROM {table}")
            if valid_rows:
                columns = list(valid_rows[0].keys())
                placeholders = ", ".join(["?"] * len(columns))
                col_names = ", ".join(columns)
                cursor.executemany(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                    [tuple(r.get(c) for c in columns) for r in valid_rows],
                )
            imported[table] = len(valid_rows)

        if _read_protected_settings(cursor) != protected_before:
            raise RuntimeError("Backup import would change protected settings")

        reassigned = _detach_reassigned_devices(cursor, devices_before, frozenset(imported))
        _drop_orphaned_rack_rows(cursor)
        if report is not None:
            cursor.execute("SELECT COUNT(*) FROM agent_tokens")
            report["agent_tokens_revoked"] = tokens_before - cursor.fetchone()[0]
            report["reassigned_device_ids"] = reassigned

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


async def restore_upload(request: Request, file: UploadFile, db: AsyncSession, actor: str | None = None) -> dict:
    """Check, write and clean up after an uploaded backup; used by the import and the setup wizard."""
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
    await audit(request, "backup.import", detail=f"{imported.get('devices', 0)} devices, {imported.get('app_settings', 0)} settings", actor=actor)

    reassigned = report.get("reassigned_device_ids", [])
    revoked = report.get("agent_tokens_revoked", 0)
    if reassigned:
        # Revoke first: the import is committed, and an old install code must not be redeemed
        # while the measurement data is still being deleted
        await _revoke_device_grants(reassigned)
        await _purge_telemetry(db, reassigned)
        logger.warning(
            "Backup: %d device id(s) now name other devices; removed their agent tokens (%d), interfaces and "
            "measurement data", len(reassigned), revoked,
        )

    invalidate_all_runtime_caches()

    message = "Backup successfully imported"
    if revoked:
        message += f". {revoked} agent(s) belonged to devices that are different now and must be enrolled again"
    return {
        "status": "ok",
        "message": message,
        "agent_tokens_revoked": revoked,
        "reassigned_devices": len(reassigned),
        "devices": imported.get("devices", 0),
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
