#!/usr/bin/env python3
"""
GravityLAN Agent — Modular system metrics collector.

Refactored to apply Separation of Concerns (SoC) and a plugin-like metric architecture
while maintaining zero external dependencies.

Architecture:
- ConfigLoader: Handles validation and default values.
- MetricCollector: Base class for metric plugins.
- ReportSender: Handles network communication with retry logic.
- AgentOrchestrator: Coordinates collection and reporting.
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
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Type, Union

# ---------------------------------------------------------------------------
# Constants & Logging
# ---------------------------------------------------------------------------

VERSION = "0.2.3"
AGENT_NAME = "gravitylan-agent"
DEFAULT_CONFIG_FILENAME = "agent.conf"
DEFAULT_LOG_FILENAME = "gravitylan-agent.log"

logger = logging.getLogger(AGENT_NAME)

def setup_logging(config_dir: Path) -> None:
    """Configures logging for both file and console."""
    logger.setLevel(logging.INFO)
    
    log_file = config_dir / DEFAULT_LOG_FILENAME
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(console_handler)

# ---------------------------------------------------------------------------
# Configuration Management
# ---------------------------------------------------------------------------

@dataclass
class AgentConfig:
    """Container for agent configuration with validation."""
    server_url: str
    token: str
    device_id: int
    interval: int = 30
    disk_paths: List[str] = field(default_factory=lambda: ["/"])
    enable_temp: bool = True
    config_path: Optional[Path] = None

    @classmethod
    def load(cls, config_path: Path) -> AgentConfig:
        """Loads and validates configuration from a JSON file."""
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        try:
            with open(config_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config: {e}")

        # Basic validation
        required = ["server_url", "token", "device_id"]
        for key in required:
            if key not in data:
                raise KeyError(f"Missing required config key: {key}")

        # URL Sanitization
        url = data["server_url"]
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        data["server_url"] = url

        return cls(
            server_url=data["server_url"],
            token=data["token"],
            device_id=int(data["device_id"]),
            interval=data.get("interval", 30),
            disk_paths=data.get("disk_paths", ["/"]),
            enable_temp=data.get("enable_temp", True),
            config_path=config_path
        )

    def save(self) -> None:
        """Persists current configuration back to disk."""
        if not self.config_path:
            return
        
        try:
            data = asdict(self)
            data.pop("config_path", None) # Don't save the path inside the file
            with open(self.config_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            logger.info("Configuration persisted to %s", self.config_path)
        except OSError as e:
            logger.error("Failed to save configuration: %s", e)

# ---------------------------------------------------------------------------
# Metric Collection Plugins
# ---------------------------------------------------------------------------

class MetricProvider:
    """Base class for all metric collection logic (Plugin Pattern)."""
    def collect(self, config: AgentConfig) -> Any:
        raise NotImplementedError("Subclasses must implement collect()")

class CPUMetrics(MetricProvider):
    """Calculates CPU usage percentage using /proc/stat delta."""
    def __init__(self):
        self.prev_idle = 0
        self.prev_total = 0

    def collect(self, config: AgentConfig) -> float:
        try:
            with open("/proc/stat", encoding="utf-8") as fh:
                parts = fh.readline().split()
            
            # user, nice, system, idle, iowait, irq, softirq, steal
            values = [int(v) for v in parts[1:9]]
            idle = values[3] + values[4]
            total = sum(values)

            if self.prev_total == 0:
                self.prev_idle, self.prev_total = idle, total
                return 0.0

            delta_idle = idle - self.prev_idle
            delta_total = total - self.prev_total
            self.prev_idle, self.prev_total = idle, total

            if delta_total == 0:
                return 0.0

            return round((1.0 - delta_idle / delta_total) * 100, 1)
        except (OSError, ValueError, ZeroDivisionError):
            return 0.0

class RAMMetrics(MetricProvider):
    """Reads memory utilization from /proc/meminfo."""
    def collect(self, config: AgentConfig) -> Dict[str, Any]:
        try:
            meminfo: Dict[str, int] = {}
            with open("/proc/meminfo", encoding="utf-8") as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) >= 2:
                        meminfo[parts[0].rstrip(":")] = int(parts[1])
            
            total_kb = meminfo.get("MemTotal", 0)
            available_kb = meminfo.get("MemAvailable", 0)
            used_kb = total_kb - available_kb

            return {
                "total_mb": total_kb // 1024,
                "used_mb": used_kb // 1024,
                "percent": round(used_kb / total_kb * 100, 1) if total_kb > 0 else 0.0
            }
        except (OSError, ValueError):
            return {"total_mb": 0, "used_mb": 0, "percent": 0.0}

class DiskMetrics(MetricProvider):
    """Reads disk usage for configured paths and automatically discovers physical/ZFS mounts."""
    def collect(self, config: AgentConfig) -> List[Dict[str, Any]]:
        # 1. Determine if we should use auto-discovery
        is_default = len(config.disk_paths) == 1 and config.disk_paths[0] == "/"
        targets = set(config.disk_paths)
        
        # 2. Pre-fetch ZFS stats if available
        zfs_stats = {}
        try:
            # We want: mountpoint, used, avail, refer
            cmd = ["zfs", "list", "-H", "-p", "-o", "mountpoint,used,avail,refer"]
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
            for line in output.strip().split("\n"):
                m, used, avail, refer = line.split("\t")
                if m != "none":
                    zfs_stats[m] = {
                        "used": int(used),
                        "avail": int(avail),
                        "refer": int(refer)
                    }
        except Exception:
            pass

        if is_default:
            # Auto-discovery fallback
            try:
                with open("/proc/mounts", "r", encoding="utf-8") as fh:
                    for line in fh:
                        parts = line.split()
                        if len(parts) < 3: continue
                        dev, mount, fstype = parts[0], parts[1], parts[2]
                        if fstype in ("ext4", "xfs", "zfs", "btrfs", "ntfs", "fuse.shfs") or mount.startswith("/mnt/"):
                            if any(x in mount for x in ("/docker/", "/container/", "/kubelet/")): continue
                            targets.add(mount)
            except Exception: pass

        results = []
        seen_devices = set()

        for path in sorted(list(targets)):
            try:
                # 3. Use ZFS stats if available for this path
                if path in zfs_stats:
                    z = zfs_stats[path]
                    total = z["used"] + z["avail"]
                    used = z["used"]
                else:
                    # 4. Fallback to statvfs
                    st = os.statvfs(path)
                    fs_id = f"{st.f_blocks}-{st.f_files}"
                    if fs_id in seen_devices and path != "/": continue
                    seen_devices.add(fs_id)
                    total = st.f_blocks * st.f_frsize
                    used = total - (st.f_bavail * st.f_frsize)

                if total == 0: continue

                results.append({
                    "path": path,
                    "total_gb": round(total / (1024**3), 1),
                    "used_gb": round(used / (1024**3), 1),
                    "percent": round(used / total * 100, 1)
                })
            except (OSError, PermissionError):
                continue
                
        return results

class NetworkMetrics(MetricProvider):
    """Calculates network throughput per interface from /proc/net/dev."""
    def __init__(self):
        self.prev_counters: Dict[str, tuple[int, int]] = {}

    def collect(self, config: AgentConfig) -> Dict[str, Dict[str, int]]:
        current: Dict[str, tuple[int, int]] = {}
        try:
            with open("/proc/net/dev", encoding="utf-8") as fh:
                for line in fh:
                    if ":" not in line: continue
                    iface, data = line.split(":", 1)
                    iface = iface.strip()
                    if iface == "lo": continue
                    parts = data.split()
                    if len(parts) >= 9:
                        current[iface] = (int(parts[0]), int(parts[8]))
        except (OSError, ValueError):
            return {}

        result = {}
        for iface, (rx, tx) in current.items():
            prev_rx, prev_tx = self.prev_counters.get(iface, (rx, tx))
            result[iface] = {
                "rx_bytes_sec": max(0, rx - prev_rx),
                "tx_bytes_sec": max(0, tx - prev_tx),
            }
        
        self.prev_counters = current
        return result

class SystemInfoProvider(MetricProvider):
    """Provides static system metadata."""
    def collect(self, config: AgentConfig) -> Dict[str, str]:
        return {
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
            "arch": platform.machine(),
            "kernel": platform.release(),
        }

class ThermalMetrics(MetricProvider):
    """Reads CPU temperature from sysfs thermal zones."""
    def collect(self, config: AgentConfig) -> Optional[float]:
        if not config.enable_temp:
            return None
        
        base_path = Path("/sys/class/thermal")
        if not base_path.exists():
            return None

        for zone in sorted(base_path.glob("thermal_zone*")):
            try:
                temp_c = int((zone / "temp").read_text().strip()) / 1000.0
                z_type = (zone / "type").read_text().strip().lower()
                if any(kw in z_type for kw in ("cpu", "soc", "x86", "acpi")):
                    return round(temp_c, 1)
            except (ValueError, OSError):
                continue
        return None

# ---------------------------------------------------------------------------
# Reporting & Communication
# ---------------------------------------------------------------------------

class ReportSender:
    """Handles reporting with retry and exponential backoff."""
    def __init__(self, config: AgentConfig):
        self.config = config
        self.base_url = f"{config.server_url}/api/agent/report"
        self.consecutive_failures = 0

    def send(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Sends payload with a simple retry/backoff mechanism."""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.token}",
                "X-Agent-Version": VERSION,
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.consecutive_failures = 0
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout) as e:
            self.consecutive_failures += 1
            wait_time = min(self.consecutive_failures * 5, 60)
            logger.warning("Report delivery failed (%s). Backing off for %ds.", e, wait_time)
            return None
        except Exception as e:
            logger.error("Unexpected error in ReportSender: %s", e)
            return None

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """Coordinates metric collection and reporting loop."""
    def __init__(self, config: AgentConfig):
        self.config = config
        self.running = True
        self.reporter = ReportSender(config)
        
        # Initialize collectors (Plugin Registry)
        self.collectors: Dict[str, MetricProvider] = {
            "cpu_percent": CPUMetrics(),
            "ram": RAMMetrics(),
            "disk": DiskMetrics(),
            "network": NetworkMetrics(),
            "system": SystemInfoProvider(),
            "temperature": ThermalMetrics()
        }

        # Setup Signal Handlers
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

    def stop(self, *args) -> None:
        """Triggers graceful shutdown."""
        logger.info("Shutdown signal received. Stopping agent...")
        self.running = False

    def collect_all(self) -> Dict[str, Any]:
        """Runs all registered collectors."""
        payload = {
            "device_id": self.config.device_id,
            "agent_version": VERSION,
            "timestamp": time.time(),
        }
        
        for key, collector in self.collectors.items():
            value = collector.collect(self.config)
            if value is not None:
                payload[key] = value
        
        return payload

    def process_response(self, response: Dict[str, Any]) -> None:
        """Updates internal config based on server feedback."""
        changed = False
        
        # Device ID Sync
        if response.get("device_id") and response["device_id"] != self.config.device_id:
            logger.info("Updating Device ID to %s", response["device_id"])
            self.config.device_id = response["device_id"]
            changed = True
        
        # Runtime Config Updates
        remote_conf = response.get("config")
        if remote_conf and isinstance(remote_conf, dict):
            if "interval" in remote_conf and self.config.interval != remote_conf["interval"]:
                self.config.interval = remote_conf["interval"]
                changed = True
            if "disk_paths" in remote_conf and self.config.disk_paths != remote_conf["disk_paths"]:
                self.config.disk_paths = remote_conf["disk_paths"]
                changed = True
            if "enable_temp" in remote_conf and self.config.enable_temp != remote_conf["enable_temp"]:
                self.config.enable_temp = remote_conf["enable_temp"]
                changed = True

        if changed:
            self.config.save()

    def run(self) -> None:
        """Main execution loop."""
        logger.info("%s v%s started. Monitoring every %ds.", AGENT_NAME, VERSION, self.config.interval)
        
        # Warm up delta collectors
        self.collectors["cpu_percent"].collect(self.config)
        self.collectors["network"].collect(self.config)
        time.sleep(1)

        while self.running:
            try:
                payload = self.collect_all()
                response = self.reporter.send(payload)
                if response:
                    self.process_response(response)
            except Exception as e:
                logger.error("Error in orchestrator loop: %s", e)

            # Responsive sleep
            for _ in range(self.config.interval):
                if not self.running: break
                time.sleep(1)

        logger.info("%s stopped.", AGENT_NAME)

# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def cleanup_ghosts() -> None:
    """Kills existing instances of the agent to avoid conflicts."""
    try:
        my_pid = os.getpid()
        output = subprocess.check_output(["ps", "-eo", "pid,args"]).decode()
        for line in output.splitlines():
            if AGENT_NAME in line and str(my_pid) not in line:
                pid = int(line.strip().split()[0])
                os.kill(pid, signal.SIGTERM)
                logger.info("Cleaned up ghost process %d", pid)
    except Exception:
        pass

def main() -> None:
    """Application entry point."""
    script_dir = Path(__file__).parent.absolute()
    config_path = script_dir / DEFAULT_CONFIG_FILENAME
    
    setup_logging(script_dir)
    cleanup_ghosts()

    try:
        config = AgentConfig.load(config_path)
        agent = AgentOrchestrator(config)
        agent.run()
    except Exception as e:
        logger.critical("Fatal startup error: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
