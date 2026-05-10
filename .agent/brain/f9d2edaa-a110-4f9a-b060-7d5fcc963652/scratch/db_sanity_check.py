import sqlite3
import json

db_path = r'\\unraid\appdata\gravitylan\data\gravitylan.db'

def check_db():
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        print("--- Basic Integrity ---")
        cur.execute("PRAGMA integrity_check;")
        print(f"Integrity: {cur.fetchone()[0]}")
        
        cur.execute("PRAGMA foreign_key_check;")
        fk_errors = cur.fetchall()
        print(f"Foreign Key Errors: {len(fk_errors)}")
        for err in fk_errors:
            print(f"  - Table {err[0]}, Row {err[1]}, Refers to {err[2]} (Error: {err[3]})")

        print("\n--- Orphaned Records ---")
        # Tokens without devices
        cur.execute("SELECT COUNT(*) FROM agent_tokens WHERE device_id NOT IN (SELECT id FROM devices)")
        print(f"Tokens without devices: {cur.fetchone()[0]}")
        
        # Metrics without devices
        cur.execute("SELECT COUNT(*) FROM device_metrics WHERE device_id NOT IN (SELECT id FROM devices)")
        print(f"Metrics without devices: {cur.fetchone()[0]}")
        
        # Services without devices
        cur.execute("SELECT COUNT(*) FROM services WHERE device_id NOT IN (SELECT id FROM devices)")
        print(f"Services without devices: {cur.fetchone()[0]}")

        print("\n--- Data Quality ---")
        # Devices with duplicate IPs (should be impossible due to UNIQUE, but let's check)
        cur.execute("SELECT ip, COUNT(*) FROM devices GROUP BY ip HAVING COUNT(*) > 1")
        dupe_ips = cur.fetchall()
        print(f"Duplicate IPs in devices: {len(dupe_ips)}")
        
        # Devices without a group
        cur.execute("SELECT COUNT(*) FROM devices WHERE group_id IS NULL")
        print(f"Devices without group: {cur.fetchone()[0]}")
        
        # Discovered hosts that are already in devices (should be cleaned up)
        cur.execute("SELECT COUNT(*) FROM discovered_hosts WHERE ip IN (SELECT ip FROM devices)")
        print(f"Discovered hosts already in devices: {cur.fetchone()[0]}")

        print("\n--- Agent Status ---")
        cur.execute("SELECT COUNT(*) FROM agent_tokens")
        total_tokens = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM agent_tokens WHERE is_active = 1")
        active_tokens = cur.fetchone()[0]
        print(f"Total Agent Tokens: {total_tokens}")
        print(f"Active Agent Tokens: {active_tokens}")

        conn.close()
    except Exception as e:
        print(f"Error during check: {e}")

if __name__ == "__main__":
    check_db()
