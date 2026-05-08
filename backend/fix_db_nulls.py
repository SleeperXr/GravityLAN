import sqlite3
import os
from datetime import datetime

db_path = r"E:\Users\Oliver\Etc\Projekte\Antigravity\HomeLan\backend\data\homelan.db"

if not os.path.exists(db_path):
    print(f"Database NOT found at {db_path}")
    exit(1)

print(f"Fixing database NULLs: {db_path}")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

now = datetime.now().isoformat()

# Set default for status_changed_at if NULL
cursor.execute("UPDATE devices SET status_changed_at = ? WHERE status_changed_at IS NULL", (now,))
print(f"Updated status_changed_at for existing devices.")

# Also ensure is_virtual/virtual_type have defaults if needed (though they are nullable or have defaults)
cursor.execute("UPDATE devices SET is_online = 1 WHERE is_online IS NULL")

conn.commit()
conn.close()
print("Database NULL fix complete.")
