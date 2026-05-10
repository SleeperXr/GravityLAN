import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

async def run_migrations(db: AsyncSession):
    """Run schema migrations for SQLite database.
    
    This handles adding missing columns to existing tables without breaking 
    compatibility for users with older database versions.
    """
    # Define missing columns as (table, column, type)
    migrations = [
        ("devices", "topology_x", "INTEGER"),
        ("devices", "topology_y", "INTEGER"),
        ("devices", "max_ports",  "INTEGER DEFAULT 24"),
        ("devices", "topology_config", "TEXT"),
        ("devices", "parent_id",  "INTEGER"),
        ("devices", "rack_id",    "INTEGER"),
        ("devices", "rack_unit",  "INTEGER"),
        ("devices", "rack_height","INTEGER DEFAULT 1"),
        ("devices", "is_wlan",    "BOOLEAN DEFAULT 0"),
        ("devices", "is_ap",      "BOOLEAN DEFAULT 0"),
        ("devices", "is_host",    "BOOLEAN DEFAULT 0"),
        ("topology_links", "source_handle", "TEXT"),
        ("topology_links", "target_handle", "TEXT"),
        ("discovered_hosts", "is_reserved", "BOOLEAN DEFAULT 0"),
        ("discovered_hosts", "old_ip", "VARCHAR(45)"),
        ("discovered_hosts", "ip_changed_at", "DATETIME"),
        ("discovered_hosts", "ports", "TEXT"),
    ]
    
    raw_conn = await db.connection()
    for table, column, col_type in migrations:
        try:
            # Check if column already exists via PRAGMA
            # SQLite specific - handles the metadata check safely
            result = await raw_conn.exec_driver_sql(f"PRAGMA table_info({table})")
            existing_columns = {row[1] for row in result.fetchall()}
            
            if column not in existing_columns:
                logger.info(f"Migration: Adding column '{column}' to '{table}'...")
                await raw_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                logger.info(f"Migration: Column '{column}' added successfully.")
        except Exception as e:
            # We log but continue, as some migrations might be engine-specific
            logger.error(f"Migration error on {table}.{column}: {e}")
            
    await db.commit()
    logger.info("Schema migration complete.")
