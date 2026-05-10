import sqlite3
import ipaddress

db_path = r'\\unraid\appdata\gravitylan\data\gravitylan.db'

def cleanup_db():
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        print("--- Starting Refined Cleanup ---")
        
        # 1. Cleanup orphaned device_history
        cur.execute("DELETE FROM device_history WHERE service_id IS NOT NULL AND service_id NOT IN (SELECT id FROM services)")
        print(f"Deleted {cur.rowcount} orphaned history records.")
        
        # 2. Cleanup discovered_hosts that are already devices
        cur.execute("DELETE FROM discovered_hosts WHERE ip IN (SELECT ip FROM devices)")
        print(f"Deleted {cur.rowcount} redundant discovery records.")
        
        # 3. Cleanup discovered_hosts that are NOT in allowed subnets
        cur.execute("SELECT value FROM app_settings WHERE key = 'scan_subnets'")
        setting = cur.fetchone()
        
        allowed_nets = []
        if setting and setting[0]:
            for s in setting[0].split(","):
                try: allowed_nets.append(ipaddress.ip_network(s.strip(), strict=False))
                except: pass
        
        if allowed_nets:
            cur.execute("SELECT id, ip FROM discovered_hosts")
            hosts = cur.fetchall()
            to_delete = []
            for h_id, ip in hosts:
                try:
                    ip_obj = ipaddress.IPv4Address(ip)
                    if not any(ip_obj in net for net in allowed_nets):
                        to_delete.append(h_id)
                except: to_delete.append(h_id)
            
            if to_delete:
                cur.execute(f"DELETE FROM discovered_hosts WHERE id IN ({','.join(map(str, to_delete))})")
                print(f"Deleted {len(to_delete)} out-of-bounds discovery records (e.g. Docker IPs).")

        conn.commit()
        print("--- Cleanup Complete! ---")
        conn.close()
    except Exception as e:
        print(f"Error during cleanup: {e}")

if __name__ == "__main__":
    cleanup_db()
