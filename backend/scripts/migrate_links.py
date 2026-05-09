import sqlite3
from pathlib import Path

def migrate():
    db_path = Path("data/gravitylan.db")
    if not db_path.exists():
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(topology_links)")
    columns = [row[1] for row in cursor.fetchall()]
    
    for col in ["source_handle", "target_handle"]:
        if col not in columns:
            print(f"Adding {col} to topology_links...")
            cursor.execute(f"ALTER TABLE topology_links ADD COLUMN {col} TEXT")
    
    conn.commit()
    conn.close()
    print("Link handles migration complete.")

if __name__ == "__main__":
    migrate()
