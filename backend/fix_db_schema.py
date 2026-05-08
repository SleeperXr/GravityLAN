import sqlite3
import os

def migrate_db():
    db_path = "backend/data/homelan.db"
    if not os.path.exists(db_path):
        db_path = "data/homelan.db" # Try local if run from backend dir
        
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("Checking app_settings table...")
    cursor.execute("PRAGMA table_info(app_settings)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "description" not in columns:
        print("Adding 'description' column to 'app_settings'...")
        cursor.execute("ALTER TABLE app_settings ADD COLUMN description TEXT")
        conn.commit()
        print("Migration successful.")
    else:
        print("'description' column already exists.")
    
    # Also check if we need to migrate system_settings data to app_settings
    # Actually, let's just make sure setup.complete is set correctly
    cursor.execute("SELECT COUNT(*) FROM app_settings WHERE key = 'setup.complete'")
    if cursor.fetchone()[0] == 0:
        print("Adding setup.complete=true to app_settings...")
        cursor.execute("INSERT INTO app_settings (key, value, category) VALUES ('setup.complete', 'true', 'system')")
        conn.commit()

    conn.close()

if __name__ == "__main__":
    migrate_db()
