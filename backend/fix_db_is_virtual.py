import sqlite3
import os

db_path = r"E:\Users\Oliver\Etc\Projekte\Antigravity\HomeLan\backend\data\homelan.db"

if not os.path.exists(db_path):
    print(f"Database NOT found at {db_path}")
    exit(1)

print(f"Fixing database: {db_path}")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE devices ADD COLUMN is_virtual BOOLEAN DEFAULT 0")
    print("Added 'is_virtual' column to 'devices' table.")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("Column 'is_virtual' already exists.")
    else:
        print(f"Error: {e}")

conn.commit()
conn.close()
print("Database fix complete.")
