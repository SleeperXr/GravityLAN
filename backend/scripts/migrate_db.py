import sqlite3
import os
from pathlib import Path

def migrate():
    db_path = Path("data/gravitylan.db")
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    print(f"Connecting to {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get existing columns
    cursor.execute("PRAGMA table_info(devices)")
    columns = [row[1] for row in cursor.fetchall()]
    print(f"Existing columns: {columns}")

    new_columns = [
        ("parent_id", "INTEGER"),
        ("rack_id", "INTEGER"),
        ("rack_unit", "INTEGER"),
        ("rack_height", "INTEGER DEFAULT 1"),
        ("topology_x", "INTEGER"),
        ("topology_y", "INTEGER"),
        ("max_ports", "INTEGER DEFAULT 24"),
        ("topology_config", "TEXT")
    ]

    for col_name, col_type in new_columns:
        if col_name not in columns:
            print(f"Adding column {col_name}...")
            try:
                cursor.execute(f"ALTER TABLE devices ADD COLUMN {col_name} {col_type}")
                print(f"Successfully added {col_name}")
            except Exception as e:
                print(f"Error adding {col_name}: {e}")
        else:
            print(f"Column {col_name} already exists")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
