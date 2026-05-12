"""Quick diagnostic script to run inside the GravityLAN container."""
import os, sys

print("=== Docker Socket Check ===")
sock_path = "/var/run/docker.sock"
print(f"Socket exists: {os.path.exists(sock_path)}")
if os.path.exists(sock_path):
    import stat
    st = os.stat(sock_path)
    print(f"Socket mode: {oct(st.st_mode)}")
    print(f"Socket uid/gid: {st.st_uid}/{st.st_gid}")

print(f"\nDOCKER_HOST_IP: {os.getenv('DOCKER_HOST_IP', 'NOT SET')}")

try:
    import docker
    client = docker.from_env()
    containers = client.containers.list()
    print(f"\nDocker API OK! Containers: {len(containers)}")
    for c in containers:
        print(f"  - {c.name} ({c.status})")
except Exception as e:
    print(f"\nDocker API FAILED: {e}")

print("\n=== Scanner Scheduler Check ===")
try:
    from app.scanner.scheduler import scheduler
    print(f"Scheduler running: {scheduler._running if hasattr(scheduler, '_running') else 'unknown'}")
    print(f"Scheduler task: {scheduler._task if hasattr(scheduler, '_task') else 'unknown'}")
except Exception as e:
    print(f"Scheduler import failed: {e}")
