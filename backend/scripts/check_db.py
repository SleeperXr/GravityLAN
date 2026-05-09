import sqlite3
from pathlib import Path

def check_tables():
    db_path = Path("data/gravitylan.db")
    if not db_path.exists():
        print("DB not found")
        return
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"Tables: {tables}")
    
    if "devices" in tables:
        cursor.execute("PRAGMA table_info(devices)")
        cols = [row[1] for row in cursor.fetchall()]
        print(f"Devices columns: {cols}")
    
    conn.close()

if __name__ == "__main__":
    check_tables()
