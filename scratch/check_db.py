import sqlite3
import json

db_path = "/app/data/gravitylan.db"
try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    print("--- DEVICES TABLE ---")
    cur.execute("SELECT id, ip, mac, display_name, hostname, is_online, last_seen FROM devices")
    for row in cur.fetchall():
        print(dict(row))
        
    print("\n--- DISCOVERED_HOSTS TABLE ---")
    cur.execute("SELECT id, ip, mac, hostname, custom_name, is_online FROM discovered_hosts WHERE is_online = 1")
    for row in cur.fetchall():
        print(dict(row))
        
    conn.close()
except Exception as e:
    print(f"Error: {e}")
