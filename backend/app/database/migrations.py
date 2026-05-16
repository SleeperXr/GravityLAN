import logging
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Define missing columns as (table, column, type) on module level for testability and maintainability
MIGRATIONS = [
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
    ("agent_tokens", "pending_token", "VARCHAR(64)"),
    ("agent_tokens", "pending_at", "DATETIME"),
]

async def run_migrations(db: AsyncSession):
    """Run schema migrations for SQLite or any alternative database.
    
    This handles adding missing columns to existing tables without breaking 
    compatibility for users with older database versions. Uses a dialect-agnostic
    SQLAlchemy Inspector approach.
    """
    raw_conn = await db.connection()
    
    # Group migrations by table to run inspection only once per table
    from collections import defaultdict
    migrations_by_table = defaultdict(list)
    for table, column, col_type in MIGRATIONS:
        migrations_by_table[table].append((column, col_type))
        
    for table, cols in migrations_by_table.items():
        try:
            # Dialect-agnostic column inspection using SQLAlchemy run_sync
            def check_table_and_columns(sync_conn):
                inspector = inspect(sync_conn)
                if not inspector.has_table(table):
                    return None
                return {col["name"] for col in inspector.get_columns(table)}

            table_info = await raw_conn.run_sync(check_table_and_columns)
            
            if table_info is None:
                logger.info(f"Migration: Table '{table}' does not exist yet. It will be created by init_db. Skipping migrations for it.")
                continue

            existing_columns = table_info
            
            for column, col_type in cols:
                if column not in existing_columns:
                    logger.info(f"Migration: Adding column '{column}' to '{table}'...")
                    await raw_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                    logger.info(f"Migration: Column '{column}' added successfully to '{table}'.")
        except Exception as e:
            logger.error(f"Migration error on table '{table}': {e}")
            
    await db.commit()
    logger.info("Schema migration complete.")

