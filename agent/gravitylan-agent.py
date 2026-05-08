#!/usr/bin/env python3
"""GravityLAN Agent — Lightweight system metrics collector.

Reads CPU, RAM, disk, temperature, and network metrics from /proc and /sys,
then POSTs them to the GravityLAN server at a configurable interval.

Zero external dependencies — uses only Python stdlib.
Designed for Linux ARM64/x86_64 (Raspberry Pi, servers, VMs).
"""

from __future__ import annotations

import json
import logging
import os
import platform
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Look for config in the same directory as the script
CONFIG_DIR = Path(__file__).parent.absolute()
CONFIG_PATH = CONFIG_DIR / "agent.conf"
VERSION = "0.1.0"

logger = logging.getLogger("gravitylan-agent")
logger.setLevel(logging.INFO)

# File logging for debugging remote deployments
log_file = CONFIG_DIR / "gravitylan-agent.log"
file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Console logging
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(console_handler)


def load_config() -> dict[str, Any]:
    """Load agent configuration from JSON config file.

    Returns:
        Configuration dictionary with server_url, token, interval, etc.

    Raises:
        SystemExit: If config file is missing or invalid.
    """
    if not CONFIG_PATH.exists():
        logger.critical("Config file not found: %s", CONFIG_PATH)
        sys.exit(1)

    with open(CONFIG_PATH, encoding="utf-8") as fh:
        config = json.load(fh)

    required_keys = ("server_url", "token", "device_id")
    for key in required_keys:
        if key not in config:
            logger.critical("Missing required config key: %s", key)
            sys.exit(1)

    # Ensure server_url has a protocol
    if not config["server_url"].startswith(("http://", "https://")):
        logger.info("Adding missing http:// prefix to server_url")
        config["server_url"] = f"http://{config['server_url']}"

    config.setdefault("interval", 30)
    config.setdefault("disk_paths", ["/"])
    config.setdefault("enable_temp", True)
    return config


# ---------------------------------------------------------------------------
# Metric Collectors — read directly from /proc and /sys (zero-dependency)
# ---------------------------------------------------------------------------

_prev_cpu: tuple[int, int] | None = None


def collect_cpu() -> float:
    """Read CPU utilization percentage from /proc/stat.

    Uses delta between two readings to calculate accurate usage.
    First call returns 0.0 since there is no previous sample.

    Returns:
        CPU usage percentage (0.0 – 100.0).
    """
    global _prev_cpu

    with open("/proc/stat", encoding="utf-8") as fh:
        parts = fh.readline().split()

    # user, nice, system, idle, iowait, irq, softirq, steal
    values = [int(v) for v in parts[1:9]]
    idle = values[3] + values[4]
    total = sum(values)

    if _prev_cpu is None:
        _prev_cpu = (idle, total)
        return 0.0

    prev_idle, prev_total = _prev_cpu
    _prev_cpu = (idle, total)

    delta_idle = idle - prev_idle
    delta_total = total - prev_total

    if delta_total == 0:
        return 0.0

    return round((1.0 - delta_idle / delta_total) * 100, 1)


def collect_ram() -> dict[str, int]:
    """Read RAM usage from /proc/meminfo.

    Returns:
        Dictionary with 'total_mb', 'used_mb', and 'percent' keys.
    """
    meminfo: dict[str, int] = {}

    with open("/proc/meminfo", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            key = parts[0].rstrip(":")
            meminfo[key] = int(parts[1])

    total_kb = meminfo.get("MemTotal", 0)
    available_kb = meminfo.get("MemAvailable", 0)
    used_kb = total_kb - available_kb

    total_mb = total_kb // 1024
    used_mb = used_kb // 1024
    percent = round(used_kb / total_kb * 100, 1) if total_kb > 0 else 0.0

    return {"total_mb": total_mb, "used_mb": used_mb, "percent": percent}


def collect_disk(paths: list[str]) -> list[dict[str, Any]]:
    """Read disk usage for the given mount paths.

    Uses 'df' command on Linux for better accuracy with ZFS/Unraid pools,
    falling back to os.statvfs if needed.
    """
    results: list[dict[str, Any]] = []

    for mount_path in paths:
        try:
            # Try 'df' first for better accuracy with ZFS pools/quotas
            # -B1 gives output in bytes
            cmd = ["df", "-B1", mount_path]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode()
            lines = output.strip().split("\n")
            if len(lines) > 1:
                # We take the last line and parse from the end to be safe with long names
                parts = lines[-1].split()
                if len(parts) >= 4:
                    # df -B1 output: Filesystem 1B-blocks Used Available Use% Mounted
                    # We take the last 5 elements to identify size components correctly
                    # regardless of how many spaces the filesystem name has.
                    # Correct mapping from end: 
                    # [-1]: mountpoint, [-2]: percent, [-3]: avail, [-4]: used, [-5]: total
                    fs_name = parts[0]
                    total = int(parts[-5])
                    used = int(parts[-4])
                    avail = int(parts[-3])
                    
                    # Special handling for ZFS: Unraid UI shows Pool stats, but df shows Dataset stats.
                    # We try to use 'zfs list' to get the full pool usage if it's a zfs mount.
                    try:
                        # Check if it's ZFS (df -T or just check if zfs command exists)
                        zfs_cmd = ["zfs", "list", "-H", "-o", "used,avail", "-p", fs_name]
                        zfs_output = subprocess.check_output(zfs_cmd, stderr=subprocess.DEVNULL).decode()
                        zfs_parts = zfs_output.strip().split()
                        if len(zfs_parts) >= 2:
                            # zfs 'used' includes all datasets/snapshots in the pool/hierarchy
                            z_used = int(zfs_parts[0])
                            z_avail = int(zfs_parts[1])
                            total = z_used + z_avail
                            used = z_used
                    except Exception:
                        pass # Not ZFS or zfs command missing, stay with df values
                    
                    # Use base 1000 for GB to match Unraid/Consumer OS display
                    total_gb = round(total / (1000 ** 3), 1)
                    used_gb = round(used / (1000 ** 3), 1)
                    percent = round(used / total * 100, 1) if total > 0 else 0.0

                    results.append({
                        "path": mount_path,
                        "total_gb": total_gb,
                        "used_gb": used_gb,
                        "percent": percent,
                    })
                    continue

        except Exception as exc:
            logger.debug("df failed for %s: %s", mount_path, exc)

        try:
            st = os.statvfs(mount_path)
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used = total - free
            # Use base 1000 for GB to match Unraid/Consumer OS display
            total_gb = round(total / (1000 ** 3), 1)
            used_gb = round(used / (1000 ** 3), 1)
            percent = round(used / total * 100, 1) if total > 0 else 0.0

            results.append({
                "path": mount_path,
                "total_gb": total_gb,
                "used_gb": used_gb,
                "percent": percent,
            })
        except OSError as exc:
            logger.warning("Cannot read disk for %s: %s", mount_path, exc)

    return results


def collect_temperature() -> float | None:
    """Read CPU temperature from /sys/class/thermal.

    Scans thermal zones for CPU-related entries. Returns None if
    temperature monitoring is not available (e.g. in virtual machines).

    Returns:
        Temperature in Celsius or None if unavailable.
    """
    thermal_base = Path("/sys/class/thermal")

    if not thermal_base.exists():
        return None

    for zone in sorted(thermal_base.glob("thermal_zone*")):
        temp_file = zone / "temp"
        type_file = zone / "type"

        if not temp_file.exists():
            continue

        try:
            temp_raw = temp_file.read_text().strip()
            temp_c = int(temp_raw) / 1000.0

            # Prefer CPU-related thermal zones
            if type_file.exists():
                zone_type = type_file.read_text().strip().lower()
                if any(kw in zone_type for kw in ("cpu", "soc", "x86", "acpi")):
                    return round(temp_c, 1)

            # Fallback: return first valid reading
            return round(temp_c, 1)
        except (ValueError, OSError):
            continue

    return None


_prev_net: dict[str, tuple[int, int]] | None = None


def collect_network() -> dict[str, dict[str, int]]:
    """Read network I/O counters from /proc/net/dev.

    Calculates bytes/sec delta between calls for each interface.
    First call returns zero rates since there is no previous sample.

    Returns:
        Dict mapping interface names to {'rx_bytes_sec', 'tx_bytes_sec'}.
    """
    global _prev_net

    current: dict[str, tuple[int, int]] = {}

    with open("/proc/net/dev", encoding="utf-8") as fh:
        for line in fh:
            if ":" not in line:
                continue
            iface, data = line.split(":", 1)
            iface = iface.strip()
            if iface == "lo":
                continue
            parts = data.split()
            rx_bytes = int(parts[0])
            tx_bytes = int(parts[8])
            current[iface] = (rx_bytes, tx_bytes)

    if _prev_net is None:
        _prev_net = current
        return {iface: {"rx_bytes_sec": 0, "tx_bytes_sec": 0} for iface in current}

    result: dict[str, dict[str, int]] = {}
    for iface, (rx, tx) in current.items():
        prev_rx, prev_tx = _prev_net.get(iface, (rx, tx))
        result[iface] = {
            "rx_bytes_sec": max(0, rx - prev_rx),
            "tx_bytes_sec": max(0, tx - prev_tx),
        }

    _prev_net = current
    return result


def collect_system_info() -> dict[str, str]:
    """Collect static system information (hostname, OS, architecture).

    Returns:
        Dictionary with 'hostname', 'os', 'arch', 'kernel' keys.
    """
    return {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "kernel": platform.release(),
    }


# ---------------------------------------------------------------------------
# Report Sender
# ---------------------------------------------------------------------------

def send_report(config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any] | None:
    """POST metrics payload to GravityLAN server.

    Args:
        config: Agent configuration containing server_url and token.
        payload: Metrics data to send.

    Returns:
        Server response as dict, or None on failure.
    """
    url = f"{config['server_url']}/api/agent/report"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['token']}",
            "X-Agent-Version": VERSION,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        logger.error("Server returned %d: %s", exc.code, exc.reason)
    except urllib.error.URLError as exc:
        logger.warning("Cannot reach server: %s", exc.reason)
    except Exception as exc:
        logger.error("Unexpected error sending report: %s", exc)

    return None


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------

_running = True


def _handle_signal(signum: int, frame: Any) -> None:
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    global _running
    logger.info("Received signal %d, shutting down...", signum)
    _running = False


def _cleanup_old_processes() -> None:
    """Find and kill other running agent processes to prevent conflicts."""
    try:
        my_pid = os.getpid()
        # Be very specific to avoid killing ourselves
        search_patterns = ["gravitylan-agent.py", "homelan-agent.py"]
        
        # Use ps with full command line to find ghosts even if they were started with just 'python'
        output = subprocess.check_output(["ps", "-eo", "pid,args"], stderr=subprocess.STDOUT).decode()
        
        for line in output.splitlines():
            line = line.strip()
            if not line: continue
            
            parts = line.split(None, 1)
            if len(parts) < 2: continue
            
            try:
                pid = int(parts[0])
                cmd = parts[1]
            except ValueError:
                continue

            if pid == my_pid:
                continue

            if any(p in cmd for p in search_patterns):
                # Extra safety: don't kill the installer bash script or curl
                if "bash" in cmd or "curl" in cmd: continue
                
                logger.info(f"Killing ghost process {pid}: {cmd}")
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError: pass
    except Exception:
        pass


def main() -> None:
    """Agent main entry point — collect and report metrics in a loop."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # First, clean up any old instances to avoid 401/conflict errors
    _cleanup_old_processes()

    logger.info("GravityLAN Agent v%s starting...", VERSION)
    config = load_config()
    logger.info(
        "Reporting to %s every %ds (device_id=%s)",
        config["server_url"],
        config["interval"],
        config["device_id"],
    )

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Initial CPU reading (needs two samples for delta)
    collect_cpu()
    time.sleep(1)

    while _running:
        try:
            payload: dict[str, Any] = {
                "device_id": config["device_id"],
                "agent_version": VERSION,
                "timestamp": time.time(),
                "cpu_percent": collect_cpu(),
                "ram": collect_ram(),
                "disk": collect_disk(config.get("disk_paths", ["/"])),
                "network": collect_network(),
                "system": collect_system_info(),
            }

            if config.get("enable_temp", True):
                temp = collect_temperature()
                if temp is not None:
                    payload["temperature"] = temp

            response = send_report(config, payload)

            if response and isinstance(response, dict):
                # Server can push config updates (e.g. new interval)
                config_changed = False
                
                # Check for device_id sync (Auto-healing after server reset)
                if response.get("device_id") and response["device_id"] != config["device_id"]:
                    logger.info("Device ID updated from server: %s -> %s", config["device_id"], response["device_id"])
                    config["device_id"] = response["device_id"]
                    config_changed = True

                new_conf = response.get("config")
                if new_conf and isinstance(new_conf, dict):
                    if "interval" in new_conf and config["interval"] != new_conf["interval"]:
                        config["interval"] = new_conf["interval"]
                        config_changed = True
                    if "disk_paths" in new_conf and config["disk_paths"] != new_conf["disk_paths"]:
                        config["disk_paths"] = new_conf["disk_paths"]
                        config_changed = True
                    if "enable_temp" in new_conf and config["enable_temp"] != new_conf["enable_temp"]:
                        config["enable_temp"] = new_conf["enable_temp"]
                        config_changed = True
                
                if config_changed:
                    logger.info("Persisting updated configuration to agent.conf")
                    try:
                        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                            json.dump(config, fh, indent=2)
                    except Exception as e:
                        logger.error("Failed to save updated config: %s", e)

        except Exception as exc:
            logger.error("Error in collection loop: %s", exc)

        # Sleep in small increments for responsive shutdown
        for _ in range(config["interval"]):
            if not _running:
                break
            time.sleep(1)

    logger.info("GravityLAN Agent stopped.")


if __name__ == "__main__":
    main()
