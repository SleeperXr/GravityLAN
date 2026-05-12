"""Force the Docker host online and check scheduler."""
import sqlite3, os, sys
from datetime import datetime

db_path = "/app/data/gravitylan.db"
host_ip = os.getenv("DOCKER_HOST_IP", "192.168.100.37")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check current state of .37
cursor.execute("SELECT id, ip, display_name, is_online, last_seen FROM devices WHERE ip = ?", (host_ip,))
row = cursor.fetchone()
if row:
    print(f"Device: id={row[0]}, ip={row[1]}, name={row[2]}, online={row[3]}, last_seen={row[4]}")
    # Force it online
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE devices SET is_online = 1, last_seen = ? WHERE ip = ?", (now, host_ip))
    conn.commit()
    print(f"FORCED {host_ip} ONLINE at {now}")
else:
    print(f"No device found with IP {host_ip}")

# Check device count
cursor.execute("SELECT COUNT(*) FROM devices")
print(f"\nTotal devices: {cursor.fetchone()[0]}")

# Check topology_links
cursor.execute("SELECT COUNT(*) FROM topology_links")
print(f"Total topology links: {cursor.fetchone()[0]}")

conn.close()
