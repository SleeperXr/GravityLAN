import sqlite3
import os

db_path = r"E:\Users\Oliver\Etc\Projekte\Antigravity\HomeLan\backend\data\homelan.db"

if not os.path.exists(db_path):
    print(f"Database NOT found at {db_path}")
    exit(1)

print(f"Creating discovered_hosts table: {db_path}")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS discovered_hosts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip VARCHAR(45) NOT NULL UNIQUE,
            mac VARCHAR(17),
            hostname VARCHAR(255),
            vendor VARCHAR(100),
            first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_online BOOLEAN DEFAULT 1
        )
    """)
    print("Table 'discovered_hosts' created successfully.")
except sqlite3.OperationalError as e:
    print(f"Error: {e}")

conn.commit()
conn.close()
print("Database table creation complete.")
