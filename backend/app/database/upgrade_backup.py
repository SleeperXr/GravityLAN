"""A copy of the inventory database before a new version migrates it.

On start, ``.last_version`` in the data directory names the version that last migrated the database. When the
running version differs, the database is copied to ``backups/gravitylan-<old version>-<UTC time>.db`` before
anything touches the schema, and the newest ``KEEP`` copies stay. The version is written again only after the
migrations ran, so a start that fails half-way copies again next time and keeps the earlier copies.

Only the SQLite database in the data directory is copied. Measurement data (telemetry.db) is left out on
purpose: it can be large and is not needed to go back. An external database (GRAVITYLAN_DATABASE_URL) is the
operator's to back up.
"""
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

KEEP = 3
VERSION_FILE = ".last_version"
BACKUP_DIR = "backups"
PREFIX = "gravitylan-"


def _has_inventory(db_path: Path) -> bool:
    """Whether the file holds a GravityLAN database (a fresh install may already have an empty file)."""
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return False
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings'").fetchone()
        return row is not None
    finally:
        conn.close()


def _read_last_version(data_dir: Path) -> str | None:
    try:
        return (data_dir / VERSION_FILE).read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def _safe_label(version: str) -> str:
    return "".join(c if c.isalnum() or c in ".-+" else "_" for c in version)


def _copy(db_path: Path, target: Path) -> None:
    """A consistent copy through SQLite's backup API, written under a temporary name first."""
    partial = target.with_suffix(".partial")
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(partial)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    partial.replace(target)


def _prune(backup_dir: Path, keep: int) -> None:
    copies = sorted(backup_dir.glob(f"{PREFIX}*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in copies[keep:]:
        old.unlink(missing_ok=True)


def backup_before_upgrade(data_dir: Path, db_path: Path, version: str, keep: int = KEEP) -> Path | None:
    """Copy the database when it was last migrated by another version; returns the copy, if one was made."""
    last = _read_last_version(data_dir)
    if last == version:
        return None
    try:
        if not _has_inventory(db_path):
            return None
        backup_dir = data_dir / BACKUP_DIR
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = backup_dir / f"{PREFIX}{_safe_label(last or 'unknown')}-{stamp}.db"
        _copy(db_path, target)
        _prune(backup_dir, keep)
    except (OSError, sqlite3.Error) as e:
        # No copy is no reason to keep the server down; the log says so
        logger.error("Could not copy the database before the update to %s: %s", version, e)
        return None
    logger.info("Database copied before the update from %s to %s: %s", last or "an older version", version, target)
    return target


def remember_version(data_dir: Path, version: str) -> None:
    """Record that this version has migrated the database."""
    try:
        (data_dir / VERSION_FILE).write_text(version + "\n", encoding="utf-8")
    except OSError as e:
        logger.warning("Could not record the database version in %s: %s", data_dir / VERSION_FILE, e)
