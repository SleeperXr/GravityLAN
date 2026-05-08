import sqlite3
import os

def migrate_monitored_hosts():
    db_path = "backend/data/homelan.db"
    if not os.path.exists(db_path):
        db_path = "data/homelan.db" # Try local if run from backend dir
        
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("Migrating 'discovered_hosts' table...")
    cursor.execute("PRAGMA table_info(discovered_hosts)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "custom_name" not in columns:
        print("Adding 'custom_name' column to 'discovered_hosts'...")
        cursor.execute("ALTER TABLE discovered_hosts ADD COLUMN custom_name TEXT")
    
    if "is_monitored" not in columns:
        print("Adding 'is_monitored' column to 'discovered_hosts'...")
        cursor.execute("ALTER TABLE discovered_hosts ADD COLUMN is_monitored BOOLEAN DEFAULT 0")
    
    print("Ensuring indexes on 'mac' columns...")
    # Check if index exists on devices.mac
    cursor.execute("PRAGMA index_list(devices)")
    indexes = [idx[1] for idx in cursor.fetchall()]
    if "ix_devices_mac" not in indexes:
        print("Creating index on 'devices.mac'...")
        cursor.execute("CREATE INDEX ix_devices_mac ON devices (mac)")

    # Check if index exists on discovered_hosts.mac
    cursor.execute("PRAGMA index_list(discovered_hosts)")
    indexes = [idx[1] for idx in cursor.fetchall()]
    if "ix_discovered_hosts_mac" not in indexes:
        print("Creating index on 'discovered_hosts.mac'...")
        cursor.execute("CREATE INDEX ix_discovered_hosts_mac ON discovered_hosts (mac)")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate_monitored_hosts()
