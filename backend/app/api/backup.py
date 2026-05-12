import asyncio
import json
import sqlite3
import os
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backup", tags=["backup"])

@router.get("/export")
async def export_backup():
    """Export the current database state as a JSON file."""
    db_path = settings.effective_database_url.replace("sqlite+aiosqlite:///", "")
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Database file not found")

    def _read_db() -> dict:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        data: dict = {
            "metadata": {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "version": "0.1.0",
                "source": "GravityLAN Dashboard",
            },
            "device_groups": [],
            "devices": [],
            "services": [],
            "discovered_hosts": [],
            "settings": [],
        }
        tables = {
            "device_groups": "device_groups",
            "devices": "devices",
            "services": "services",
            "discovered_hosts": "discovered_hosts",
            "settings": "app_settings",
            "agent_tokens": "agent_tokens",
            "agent_configs": "agent_configs",
            "subnets": "subnets",
            "topology_links": "topology_links",
            "racks": "racks",
        }
        for key, table in tables.items():
            try:
                cursor.execute(f"SELECT * FROM {table}")
                data[key] = [dict(row) for row in cursor.fetchall()]
            except sqlite3.OperationalError as e:
                logger.warning(f"Backup: Table {table} skipped ({e})")
        conn.close()
        return data

    try:
        data = await asyncio.to_thread(_read_db)
        filename = f"gravitylan_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        return JSONResponse(
            content=data,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error(f"Backup: Export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import")
async def import_backup(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Import a JSON backup file into the database."""
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON files are supported")

    try:
        content = await file.read()
        data = json.loads(content)

        db_path = settings.effective_database_url.replace("sqlite+aiosqlite:///", "")

        ALLOWED_TABLE_MAP = {
            "device_groups": "device_groups",
            "devices": "devices",
            "services": "services",
            "discovered_hosts": "discovered_hosts",
            "settings": "app_settings",
            "agent_tokens": "agent_tokens",
            "agent_configs": "agent_configs",
            "subnets": "subnets",
            "topology_links": "topology_links",
            "racks": "racks",
        }

        def _write_db() -> dict:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = OFF")
            imported: dict[str, int] = {}

            for key, rows in data.items():
                if key == "metadata" or not rows:
                    continue
                if key not in ALLOWED_TABLE_MAP:
                    logger.warning(f"Backup: Skipping unauthorized table key '{key}'")
                    continue

                table = ALLOWED_TABLE_MAP[key]
                cursor.execute(f"PRAGMA table_info({table})")
                table_info = {
                    col[1]: {"notnull": col[3], "default": col[4], "type": col[2]}
                    for col in cursor.fetchall()
                }
                table_cols = set(table_info.keys())
                if not table_cols:
                    logger.error(f"Backup: Table {table} not found in DB")
                    continue

                now_str = datetime.now(timezone.utc).isoformat().replace("T", " ")
                valid_rows = []
                for row in rows:
                    clean_row = {
                        col: val
                        for col, val in row.items()
                        if col in table_cols and not (val is None and table_info[col]["notnull"])
                    }
                    for col, info in table_info.items():
                        if info["notnull"] and (col not in clean_row or clean_row[col] is None):
                            if any(t in info["type"].upper() for t in ("DATETIME", "TIMESTAMP")):
                                clean_row[col] = now_str
                            elif any(t in info["type"].upper() for t in ("INT", "BOOLEAN")):
                                clean_row[col] = 0
                            else:
                                clean_row[col] = ""
                    valid_rows.append(clean_row)

                if not valid_rows:
                    continue

                cursor.execute(f"DELETE FROM {table}")
                columns = list(valid_rows[0].keys())
                placeholders = ", ".join(["?"] * len(columns))
                col_names = ", ".join(columns)
                cursor.executemany(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                    [tuple(r.get(c) for c in columns) for r in valid_rows],
                )
                imported[table] = len(valid_rows)

            conn.commit()
            cursor.execute("PRAGMA foreign_keys = ON")
            conn.close()
            return imported

        imported = await asyncio.to_thread(_write_db)
        for table, count in imported.items():
            logger.info(f"Backup: Imported {count} rows into {table}")

        return {"status": "ok", "message": "Backup successfully imported"}

    except Exception as e:
        logger.error(f"Backup: Import failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
