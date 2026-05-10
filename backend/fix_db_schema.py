"""
Script to fix the database schema, ensuring all required columns exist.
Uses centralized db_utils for safe execution and logging.
"""

import sqlite3
from scripts.db_utils import setup_script_logging, get_db_conn

logger = setup_script_logging()

def add_column_if_missing(table: str, column: str, column_def: str):
    """Safely adds a column to a table if it doesn't already exist."""
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            # Check if column exists via PRAGMA
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [info[1] for info in cursor.fetchall()]
            
            if column not in columns:
                logger.info(f"Adding column '{column}' to table '{table}'...")
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")
                logger.info("Column added successfully.")
            else:
                logger.debug(f"Column '{column}' already exists in '{table}'.")
    except sqlite3.Error as e:
        logger.error(f"Error modifying table {table}: {e}")

def main():
    """Verifies and repairs the database schema."""
    logger.info("Starting schema verification...")
    
    # Ensure critical columns exist (examples)
    add_column_if_missing("devices", "is_virtual", "BOOLEAN DEFAULT 0")
    add_column_if_missing("devices", "virtual_type", "TEXT")
    add_column_if_missing("discovered_hosts", "hostname", "TEXT")
    
    logger.info("Schema verification complete.")

if __name__ == "__main__":
    main()
