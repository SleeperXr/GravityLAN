"""
Database utility module for maintenance and migration scripts.
Provides centralized path resolution, logging, and connection management.
"""

import logging
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

def setup_script_logging(level: int = logging.INFO) -> logging.Logger:
    """Configures a standard logging format for maintenance scripts."""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger("db_maintenance")

def get_db_path() -> Path:
    """
    Dynamically determines the path to the gravitylan.db file.
    Prioritizes persistent data directories and environment variables.
    """
    # 1. Check environment variable (highest priority)
    env_path = os.environ.get("GRAVITYLAN_DATA_DIR")
    if env_path:
        p = Path(env_path) / "gravitylan.db"
        if p.exists():
            return p

    # 2. Check directory of the running script
    current_file = Path(sys.argv[0]).resolve()
    
    # List of directories to search in order of priority
    search_dirs = [
        current_file.parent / "data",          # Same dir /data
        current_file.parent.parent / "data",   # Parent /data (if script is in scripts/)
        Path("/app/data"),                     # Standard Docker path
        current_file.parent,                   # Same dir
        current_file.parent.parent,            # Parent
    ]

    possible_names = ["gravitylan.db", "homelan.db"]
    
    for directory in search_dirs:
        for name in possible_names:
            path = directory / name
            if path.exists():
                return path

    # Default fallback
    return Path("/app/data/gravitylan.db") if os.path.exists("/app/data") else current_file.parent / "gravitylan.db"

@contextmanager
def get_db_conn() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager for a SQLite connection.
    Automatically commits on success and closes the connection.
    """
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()

def run_maintenance_sql(description: str, sql: str, params: tuple = ()):
    """Helper to run a single SQL command with logging."""
    logger = logging.getLogger("db_maintenance")
    logger.info(f"Executing: {description}")
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            logger.info(f"Success. Rows affected: {cursor.rowcount}")
            return cursor.rowcount
    except Exception as e:
        logger.error(f"Failed to execute '{description}': {e}")
        return 0
