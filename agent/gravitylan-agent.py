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

import contextlib
import ipaddress
import json
import logging
import os
import platform
import shutil
import signal
import socket
import subprocess
from subprocess import SubprocessError
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

VERSION = "0.3.14"
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
    enable_patch_check: bool = True
    enable_scanner_relay: bool = False
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
            enable_patch_check=data.get("enable_patch_check", True),
            enable_scanner_relay=data.get("enable_scanner_relay", False),
            config_path=config_path
        )

    def save(self) -> None:
        """Persists current configuration back to disk."""
        if not self.config_path:
            return
        
        try:
            data = asdict(self)
            data.pop("config_path", None) # Don't save the path inside the file
            # Write a 0600 temp file next to the config and swap it in: an interrupted
            # write must not leave an empty agent.conf (the token lives only there).
            tmp_path = f"{self.config_path}.tmp"
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_path, self.config_path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
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

def _read_if_exists(path: Path, binary: bool = False) -> Any:
    """Contents of ``path`` (text, or bytes with ``binary``); None when it is missing or unreadable."""
    try:
        if not path.exists():
            return None
        return path.read_bytes() if binary else path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def is_lxc_container(root_path: str = "") -> bool:
    """Detect if running inside an LXC container."""
    root = Path(root_path)
    # Method 1: systemd names the container type; when it says, that answer counts
    marker = _read_if_exists(root / "run/systemd/container")
    if marker is not None:
        return marker.strip() == "lxc"
    # Method 2: the cgroup path of this process
    cgroup = _read_if_exists(root / "proc/self/cgroup")
    if cgroup is not None and "lxc" in cgroup:
        return True
    # Method 3: the environment of PID 1 (if readable)
    environ = _read_if_exists(root / "proc/1/environ", binary=True)
    return environ is not None and any(item.startswith(b"container=lxc") for item in environ.split(b"\x00"))


def get_lxc_cpu_count(root_path: str = "") -> float:
    """Get the CPU limit count for the LXC container from cgroups or host count."""
    root = Path(root_path)
    limit = _cpu_limit_v2(root)
    if limit is None:
        limit = _cpu_limit_v1(root)
    # Fallback to host CPU count
    return limit if limit is not None else (os.cpu_count() or 1.0)


def _cpu_limit_v2(root: Path) -> Optional[float]:
    """CPUs allowed by cgroup v2 ``cpu.max`` ("<quota> <period>"; "max" means no limit)."""
    try:
        text = _read_if_exists(root / "sys/fs/cgroup/cpu.max")
        parts = text.strip().split() if text is not None else []
        if len(parts) == 2 and parts[0] != "max":
            limit, period = int(parts[0]), int(parts[1])
            if period > 0:
                return limit / period
    except (ValueError, IndexError) as e:
        logger.debug("Failed parsing cgroup v2 cpu.max: %s", e)
    return None


def _cpu_limit_v1(root: Path) -> Optional[float]:
    """CPUs allowed by cgroup v1 ``cpu.cfs_quota_us`` / ``cpu.cfs_period_us`` (quota -1 means no limit)."""
    quota_path = root / "sys/fs/cgroup/cpu/cpu.cfs_quota_us"
    period_path = root / "sys/fs/cgroup/cpu/cpu.cfs_period_us"
    if not (quota_path.exists() and period_path.exists()):
        return None
    try:
        quota = int(quota_path.read_text(encoding="utf-8").strip())
        period = int(period_path.read_text(encoding="utf-8").strip())
        if quota > 0 and period > 0:
            return quota / period
    except (OSError, ValueError) as e:
        logger.debug("Failed reading cgroup v1 cpu limit: %s", e)
    return None


def get_lxc_cpu_usage_ns(root_path: str = "") -> int | None:
    """Get LXC CPU total usage time in nanoseconds."""
    # Try cgroup v2
    cpu_stat_v2 = Path(root_path) / "sys/fs/cgroup/cpu.stat"
    if cpu_stat_v2.exists():
        try:
            for line in cpu_stat_v2.read_text(encoding="utf-8").splitlines():
                if line.startswith("usage_usec"):
                    return int(line.split()[1]) * 1000
        except (OSError, ValueError, IndexError) as e:
            logger.debug("Failed reading cgroup v2 cpu.stat: %s", e)

    # Try cgroup v1
    cpu_usage_v1 = Path(root_path) / "sys/fs/cgroup/cpuacct/cpuacct.usage"
    if cpu_usage_v1.exists():
        try:
            return int(cpu_usage_v1.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as e:
            logger.debug("Failed reading cgroup v1 cpuacct.usage: %s", e)

    return None


class CPUMetrics(MetricProvider):
    """Calculates CPU usage percentage using /proc/stat delta or cgroups inside LXC."""
    def __init__(self, root_path: str = "/"):
        self.root_path = root_path
        self.prev_idle = 0
        self.prev_total = 0
        self.prev_lxc_time = 0.0
        self.prev_lxc_ns = 0

    def collect(self, config: AgentConfig) -> float:
        if is_lxc_container(self.root_path):
            cpu_ns = get_lxc_cpu_usage_ns(self.root_path)
            if cpu_ns is not None:
                return self._lxc_percent(cpu_ns)

        # Fallback to standard host /proc/stat
        return self._host_percent()

    def _lxc_percent(self, cpu_ns: int) -> float:
        """CPU usage since the last cgroup sample, relative to the container's CPU limit."""
        now_time = time.time()
        if self.prev_lxc_time == 0.0:
            self.prev_lxc_time, self.prev_lxc_ns = now_time, cpu_ns
            return 0.0

        delta_ns = cpu_ns - self.prev_lxc_ns
        delta_time = now_time - self.prev_lxc_time
        self.prev_lxc_time, self.prev_lxc_ns = now_time, cpu_ns

        if delta_time <= 0 or delta_ns < 0:
            return 0.0

        cpus = get_lxc_cpu_count(self.root_path)
        delta_time_ns = delta_time * 1e9
        pct = (delta_ns / delta_time_ns) * 100.0 / cpus
        return min(100.0, max(0.0, round(pct, 1)))

    def _host_percent(self) -> float:
        """CPU usage since the last /proc/stat sample."""
        try:
            stat_path = Path(self.root_path) / "proc/stat"
            with open(stat_path, encoding="utf-8") as fh:
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
    """Reads memory utilization from /proc/meminfo or cgroups inside LXC."""
    def __init__(self, root_path: str = "/"):
        self.root_path = root_path

    def collect(self, config: AgentConfig) -> Dict[str, Any]:
        if is_lxc_container(self.root_path):
            ram_data = self._collect_lxc()
            if ram_data is not None:
                return ram_data

        # Fallback to standard /proc/meminfo
        try:
            meminfo: Dict[str, int] = {}
            meminfo_path = Path(self.root_path) / "proc/meminfo"
            with open(meminfo_path, encoding="utf-8") as fh:
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

    def _collect_lxc(self) -> Dict[str, Any] | None:
        """Collect memory metrics using cgroups inside LXC."""
        used_bytes, total_bytes = self._lxc_memory_limits()

        if used_bytes is None:
            return None

        # Fallback to /proc/meminfo MemTotal if total limit is not set
        if total_bytes is None:
            total_bytes = self._meminfo_total()

        if total_bytes is None or total_bytes == 0:
            return None

        total_mb = total_bytes // (1024 * 1024)
        used_mb = used_bytes // (1024 * 1024)
        percent = round(used_bytes / total_bytes * 100, 1)

        return {
            "total_mb": total_mb,
            "used_mb": used_mb,
            "percent": percent
        }

    def _lxc_memory_limits(self) -> tuple[int | None, int | None]:
        """Read (used_bytes, total_bytes) from cgroups v2, then v1."""
        cgroup = Path(self.root_path) / "sys/fs/cgroup"
        used_bytes, total_bytes = _cgroup_memory(cgroup / "memory.current", cgroup / "memory.max", _v2_memory_limit)
        if used_bytes is None:
            used_bytes, total_bytes = _cgroup_memory(
                cgroup / "memory/memory.usage_in_bytes", cgroup / "memory/memory.limit_in_bytes", _v1_memory_limit
            )
        return used_bytes, total_bytes

    def _meminfo_total(self) -> int | None:
        """Read MemTotal from /proc/meminfo in bytes (or None when unavailable)."""
        try:
            meminfo_path = Path(self.root_path) / "proc/meminfo"
            with open(meminfo_path, encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError) as e:
            logger.debug("Failed reading MemTotal from /proc/meminfo: %s", e)
        return None

def _v2_memory_limit(text: str) -> Optional[int]:
    value = text.strip()
    return None if value == "max" else int(value)


def _v1_memory_limit(text: str) -> Optional[int]:
    # cgroup v1 writes a huge number (close to 2**63) for "no limit"
    value = int(text.strip())
    return value if value < 2**60 else None


def _cgroup_memory(current: Path, limit: Path, parse_limit: Callable[[str], Optional[int]]) -> tuple:
    """(used, total) bytes of one cgroup version; used is None when that version is not there.

    A limit that cannot be read keeps the usage already read, like the original single try block.
    """
    if not current.exists():
        return None, None
    used = total = None
    try:
        used = int(current.read_text(encoding="utf-8").strip())
        if limit.exists():
            total = parse_limit(limit.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.debug("Failed reading cgroup memory: %s", e)
    return used, total


def _collect_zfs_stats() -> Dict[str, Dict[str, int]]:
    """Pre-fetch ZFS dataset stats: {mountpoint: {used, avail, refer}}."""
    zfs_stats: Dict[str, Dict[str, int]] = {}
    try:
        cmd = ["zfs", "list", "-H", "-p", "-o", "mountpoint,used,avail,refer"]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
        for line in output.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) == 4 and parts[0] != "none":
                zfs_stats[parts[0]] = {
                    "used": int(parts[1]),
                    "avail": int(parts[2]),
                    "refer": int(parts[3])
                }
    except (OSError, SubprocessError, ValueError) as e:
        logger.debug("ZFS stats collection skipped: %s", e)
    return zfs_stats


def _discover_mount_targets(default_paths: List[str]) -> set:
    """Auto-discover physical mounts when the default '/' config is used."""
    targets = set(default_paths)
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                dev, mount, fstype = parts[0], parts[1], parts[2]
                if fstype in ("ext4", "xfs", "zfs", "btrfs", "ntfs", "fuse.shfs") or mount.startswith("/mnt/"):
                    if any(x in mount for x in ("/docker/", "/container/", "/kubelet/")):
                        continue
                    targets.add(mount)
    except OSError as e:
        logger.debug("Could not read /proc/mounts: %s", e)
    return targets


def _disk_targets(disk_paths: List[str]) -> set:
    """The paths to report: the configured ones, or the discovered mounts when only the default '/' is set."""
    if len(disk_paths) == 1 and disk_paths[0] == "/":
        return _discover_mount_targets(disk_paths)
    return set(disk_paths)


def _path_usage(path: str, zfs_stats: Dict[str, Dict[str, int]], seen_devices: set) -> Optional[tuple]:
    """(total, used) bytes of ``path``; None for a filesystem already counted under another path."""
    # Use ZFS stats if available for this path
    if path in zfs_stats:
        z = zfs_stats[path]
        return z["used"] + z["avail"], z["used"]

    # Fallback to statvfs
    st = os.statvfs(path)
    fs_id = f"{st.f_blocks}-{st.f_files}"
    if fs_id in seen_devices and path != "/":
        return None
    seen_devices.add(fs_id)
    total = st.f_blocks * st.f_frsize
    return total, total - (st.f_bavail * st.f_frsize)


class DiskMetrics(MetricProvider):
    """Reads disk usage for configured paths and automatically discovers physical/ZFS mounts."""
    def collect(self, config: AgentConfig) -> List[Dict[str, Any]]:
        # Pre-fetch ZFS stats if available
        zfs_stats = _collect_zfs_stats()
        targets = _disk_targets(config.disk_paths)

        results = []
        seen_devices = set()

        for path in sorted(list(targets)):
            try:
                usage = _path_usage(path, zfs_stats, seen_devices)
            except (OSError, PermissionError):
                continue
            if usage is None or usage[0] == 0:
                continue

            total, used = usage
            results.append({
                "path": path,
                "total_gb": round(total / (1024**3), 1),
                "used_gb": round(used / (1024**3), 1),
                "percent": round(used / total * 100, 1)
            })

        return results

class NetworkMetrics(MetricProvider):
    """Calculates network throughput (bytes per second) per interface from /proc/net/dev."""
    def __init__(self, root_path: str = "/"):
        self.root_path = root_path
        self.prev_counters: Dict[str, tuple[int, int]] = {}
        self.prev_time: float = 0.0

    def _read_counters(self) -> Optional[Dict[str, tuple[int, int]]]:
        """(rx, tx) byte counters per interface without loopback; None when /proc/net/dev cannot be read."""
        current: Dict[str, tuple[int, int]] = {}
        try:
            with open(Path(self.root_path) / "proc/net/dev", encoding="utf-8") as fh:
                for line in fh:
                    if ":" not in line: continue
                    iface, data = line.split(":", 1)
                    iface = iface.strip()
                    if iface == "lo": continue
                    parts = data.split()
                    if len(parts) >= 9:
                        current[iface] = (int(parts[0]), int(parts[8]))
        except (OSError, ValueError):
            return None
        return current

    def collect(self, config: AgentConfig) -> Dict[str, Dict[str, int]]:
        current = self._read_counters()
        if current is None:
            return {}  # a failed read keeps the previous sample

        now = time.monotonic()
        delta_time = now - self.prev_time
        first_run = self.prev_time == 0.0 or delta_time <= 0

        result = {}
        for iface, (rx, tx) in current.items():
            if first_run:
                result[iface] = {"rx_bytes_sec": 0, "tx_bytes_sec": 0}
                continue
            prev_rx, prev_tx = self.prev_counters.get(iface, (rx, tx))
            result[iface] = {
                "rx_bytes_sec": int(max(0, rx - prev_rx) / delta_time),
                "tx_bytes_sec": int(max(0, tx - prev_tx) / delta_time),
            }

        self.prev_counters = current
        self.prev_time = now
        return result

def _read_os_release() -> Dict[str, str]:
    """KEY=value pairs of /etc/os-release without their quotes; empty when it cannot be read."""
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    release: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            release[key.strip()] = value.strip().strip('"').strip("'")
    return release


def _os_release_fields(release: Dict[str, str], current_os: str) -> Dict[str, str]:
    """The system-info fields /etc/os-release decides; ``current_os`` stays when it names no OS."""
    pretty = release.get("PRETTY_NAME") or ""
    fallback = f"{release.get('NAME', '')} {release.get('VERSION_ID', '')}".strip()
    fields = {
        "os": pretty or fallback or current_os,
        "os_name": release.get("NAME") or platform.system(),
        "os_version": release.get("VERSION_ID") or platform.release(),
    }
    if release.get("VERSION_CODENAME"):
        fields["os_codename"] = release["VERSION_CODENAME"]
    return fields


class SystemInfoProvider(MetricProvider):
    """Provides static system metadata (hostname, OS, architecture, kernel)."""
    def collect(self, config: AgentConfig) -> Dict[str, str]:
        info = {
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
            "arch": platform.machine(),
            "kernel": platform.release(),
        }
        release = _read_os_release()
        if release:
            info.update(_os_release_fields(release, info["os"]))
        return info

class ThermalMetrics(MetricProvider):
    """Reads CPU temperature from sysfs thermal zones."""
    def __init__(self, root_path: str = "/"):
        self.root_path = root_path

    def collect(self, config: AgentConfig) -> Optional[float]:
        if not config.enable_temp:
            return None

        base_path = Path(self.root_path) / "sys/class/thermal"
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

def _apt_cache_is_stale(max_age_seconds: int = 3600) -> bool:
    """True when the local apt package-list cache is older than max_age."""
    lists_dir = Path("/var/lib/apt/lists")
    if not lists_dir.is_dir():
        return True
    try:
        newest = 0.0
        for p in lists_dir.iterdir():
            if p.name.endswith("_Packages"):
                newest = max(newest, p.stat().st_mtime)
        return time.time() - newest > max_age_seconds
    except OSError:
        return True


def _run_apt_update(timeout: int = 90) -> bool:
    """Refresh apt package lists; falls back to `sudo -n` when not root."""
    for cmd in (
        ["apt-get", "update", "-o", "Acquire::Retries=1"],
        ["sudo", "-n", "apt-get", "update", "-o", "Acquire::Retries=1"],
    ):
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
            if res.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):  # OSError: the command (sudo) is not installed
            continue
    return False


# Package databases; their mtime changes whenever packages are installed or upgraded.
_PACKAGE_DB_PATHS = (
    "/var/lib/dpkg/status",
    "/var/lib/rpm/rpmdb.sqlite",
    "/var/lib/rpm/Packages",
    "/usr/lib/sysimage/rpm/rpmdb.sqlite",
)


def _package_db_mtime() -> float:
    """Newest mtime of the local package database (0.0 when none is found)."""
    newest = 0.0
    for path in _PACKAGE_DB_PATHS:
        try:
            newest = max(newest, Path(path).stat().st_mtime)
        except OSError:
            continue
    return newest


class PatchMetrics(MetricProvider):
    """Calculates package updates, security updates, and reboot requirement.

    The package-manager checks start several subprocesses (and may refresh the
    package lists), so the result is cached for ``cache_ttl`` seconds. The cache
    is dropped early when the package database changes, so finished updates show
    up in the next report instead of after up to an hour.
    """

    def __init__(self, cache_ttl: int = 3600):
        self.cache_ttl = cache_ttl
        self._last_check: float = 0.0
        self._cached_result: Optional[Dict[str, Any]] = None
        self._cached_db_mtime: float = 0.0

    def collect(self, config: AgentConfig) -> Optional[Dict[str, Any]]:
        if not getattr(config, "enable_patch_check", True):
            return None

        now = time.monotonic()
        db_mtime = _package_db_mtime()
        cache_valid = (
            self._last_check != 0.0
            and now - self._last_check < self.cache_ttl
            and db_mtime == self._cached_db_mtime
        )
        if cache_valid:
            return dict(self._cached_result) if self._cached_result else None

        result = self._check_packages()
        self._last_check = now
        self._cached_db_mtime = db_mtime
        self._cached_result = result
        return dict(result) if result else None

    def _check_packages(self) -> Optional[Dict[str, Any]]:
        """Run the package-manager checks for the first manager found."""
        result: Dict[str, Any] = {
            "patch_available": 0,
            "patch_security": 0,
            "patch_manager": None,
            "reboot_required": False,
            "major_upgrade_available": None
        }

        # 1. Debian/Ubuntu (apt)
        if shutil.which("apt-get"):
            result["patch_manager"] = "apt"
            self._collect_apt(result)

        # 2. Fedora/CentOS/RHEL (dnf/yum)
        elif shutil.which("dnf"):
            result["patch_manager"] = "dnf"
            self._collect_dnf(result)

        elif shutil.which("yum"):
            result["patch_manager"] = "yum"
            self._collect_yum(result)

        if result["patch_manager"]:
            return result
        return None

    @staticmethod
    def _count_apt_upgrades(out: str) -> tuple[int, int]:
        """Count total and security upgrades from 'apt-get -s upgrade' output."""
        available = 0
        security = 0
        for line in out.splitlines():
            if line.startswith("Inst "):
                available += 1
                if "-security" in line.lower() or "security" in line.lower():
                    security += 1
        return available, security

    def _collect_apt(self, result: Dict[str, Any]) -> None:
        """Populate patch counts via the apt package manager."""
        try:
            # Refresh package lists if the local cache is stale (>= 1h).
            # Without this, `apt-get -s upgrade` only sees stale data and
            # reports 0 updates until someone runs apt-get update manually.
            if _apt_cache_is_stale() and not _run_apt_update():
                logger.warning("apt-get update failed; using stale package cache")

            # Run simulate upgrade without locks
            cmd = ["apt-get", "-s", "-o", "Debug::NoLocking=true", "upgrade"]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=10).decode("utf-8")

            available, security = self._count_apt_upgrades(out)
            result["patch_available"] = available
            result["patch_security"] = security
        except (OSError, SubprocessError) as e:
            logger.debug("apt upgrade check failed: %s", e)

        # Check if reboot is required
        result["reboot_required"] = os.path.exists("/var/run/reboot-required")

        # Check for major release upgrade (e.g. Ubuntu 22.04 -> 24.04)
        if shutil.which("do-release-upgrade"):
            self._collect_major_upgrade(result)

    def _collect_major_upgrade(self, result: Dict[str, Any]) -> None:
        """Detect a major release upgrade (e.g. Ubuntu 22.04 -> 24.04) via do-release-upgrade."""
        try:
            cmd = ["do-release-upgrade", "-c"]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=10).decode("utf-8")
            for line in out.splitlines():
                if "New release" in line and "available" in line:
                    parts = line.split("'")
                    if len(parts) >= 3:
                        result["major_upgrade_available"] = parts[1]
        except (OSError, SubprocessError) as e:
            logger.debug("do-release-upgrade check failed: %s", e)

    def _collect_dnf(self, result: Dict[str, Any]) -> None:
        """Populate patch counts via the dnf package manager."""
        try:
            result["patch_available"] = _count_update_lines(_run_quiet(["dnf", "check-update", "--quiet"]), skip_metadata=True)
            # Security count: every non-empty line except the metadata note
            out_sec = _run_quiet(["dnf", "updateinfo", "list", "security", "--quiet"])
            result["patch_security"] = sum(1 for l in out_sec.splitlines() if l.strip() and not l.startswith("Last metadata"))
        except (OSError, SubprocessError) as e:
            logger.debug("dnf check-update failed: %s", e)

        if shutil.which("needs-restarting"):
            try:
                res = subprocess.run(["needs-restarting", "-r"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if res.returncode == 1:
                    result["reboot_required"] = True
            except (OSError, SubprocessError) as e:
                logger.debug("needs-restarting failed: %s", e)

    def _collect_yum(self, result: Dict[str, Any]) -> None:
        """Populate patch counts via the yum package manager."""
        try:
            result["patch_available"] = _count_update_lines(_run_quiet(["yum", "check-update", "--quiet"]), skip_metadata=False)
        except (OSError, SubprocessError) as e:
            logger.debug("yum check-update failed: %s", e)

def _run_quiet(cmd: List[str]) -> str:
    """stdout of a package manager query (stderr dropped, 15 s at most)."""
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
    return proc.stdout.decode("utf-8")


def _count_update_lines(out: str, skip_metadata: bool) -> int:
    """Packages in ``dnf/yum check-update`` output: lines with at least name, version and repo."""
    count = 0
    for line in (l.strip() for l in out.splitlines()):
        if len(line.split()) >= 3 and not (skip_metadata and line.startswith("Last metadata")):
            count += 1
    return count


# /proc as the agent reads it (a test points it elsewhere)
_PROC = Path("/proc")


def _usable_subnet(net: ipaddress.IPv4Network) -> bool:
    """Only /16 … /30 networks are worth probing."""
    return 16 <= net.prefixlen <= 30


def _subnets_from_ip_addr(out: str) -> List[ipaddress.IPv4Network]:
    """Networks of ``ip -4 -o addr show`` lines, loopback and too large or small ones left out."""
    networks: List[ipaddress.IPv4Network] = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[2] != "inet" or parts[3].startswith("127."):
            continue
        try:
            net = ipaddress.ip_network(parts[3], strict=False)
        except ValueError:
            continue
        if _usable_subnet(net):
            networks.append(net)
    return networks


def _hex_ip(value: str) -> str:
    """An IPv4 address as /proc/net/route writes it (little-endian hex)."""
    return socket.inet_ntoa(bytes.fromhex(value)[::-1])


def _route_line_subnet(line: str) -> Optional[ipaddress.IPv4Network]:
    """The network of one /proc/net/route line if it is a usable route that is up; raises on a malformed line."""
    parts = line.strip().split()
    if len(parts) < 8 or parts[0] == "lo":
        return None
    # Flag 0x1: route is up; the default route has destination 0
    if not (int(parts[3], 16) & 0x1) or parts[1] == "00000000":
        return None
    net = ipaddress.ip_network(f"{_hex_ip(parts[1])}/{_hex_ip(parts[7])}", strict=False)
    return net if _usable_subnet(net) else None


def _neighbors_from_proc_arp(lines: List[str]) -> Dict[str, Dict[str, str]]:
    """Completed entries of /proc/net/arp (header line first) by IP."""
    neighbors: Dict[str, Dict[str, str]] = {}
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        ip, flags, mac, dev = parts[0], parts[2], parts[3].lower(), parts[5]
        # 0x2 = ATF_COM (completed ARP resolution)
        if flags == "0x2" and mac and mac != "00:00:00:00:00:00":
            neighbors[ip] = {"ip": ip, "mac": mac, "interface": dev}
    return neighbors


def _apply_ip_neigh(neighbors: Dict[str, Dict[str, str]], out: str) -> None:
    """Add what ``ip -4 neigh show`` knows; stale, failed and incomplete entries are removed."""
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or "lladdr" not in parts:
            continue
        idx = parts.index("lladdr")
        if idx + 1 >= len(parts):
            continue
        ip, mac = parts[0], parts[idx + 1].lower()
        dev = parts[parts.index("dev") + 1] if "dev" in parts else ""
        if parts[-1].upper() in ("STALE", "FAILED", "INCOMPLETE"):
            neighbors.pop(ip, None)
        elif mac != "00:00:00:00:00:00":
            neighbors[ip] = {"ip": ip, "mac": mac, "interface": dev}


def _udp_arp_burst(net: ipaddress.IPv4Network) -> None:
    """One UDP packet per host: the kernel sends an ARP WHO-HAS for each address."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        for host in net.hosts():
            with contextlib.suppress(OSError):
                sock.sendto(b"\x00", (str(host), 55555))
        sock.close()
    except OSError as e:
        logger.debug("UDP ARP burst failed: %s", e)


def _broadcast_ping(net: ipaddress.IPv4Network) -> None:
    """A directed subnet broadcast ping, if the ping tool is there."""
    try:
        subprocess.run(
            ["ping", "-b", "-c", "1", "-W", "1", str(net.broadcast_address)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.5,
        )
    except (OSError, SubprocessError) as e:
        logger.debug("Broadcast ping failed: %s", e)


class ArpNeighborCollector(MetricProvider):
    """Collects Layer-2 ARP neighbors when enable_scanner_relay is True."""

    def __init__(self):
        self.last_probe_time = 0.0

    def collect(self, config: AgentConfig) -> Optional[List[Dict[str, str]]]:
        if not getattr(config, "enable_scanner_relay", False):
            return None

        # Periodically refresh ARP cache via lightweight UDP burst + broadcast probe (every 60 seconds)
        now = time.time()
        if now - self.last_probe_time > 60:
            self._probe_local_subnets()
            self.last_probe_time = now

        return self._read_arp_table()

    def _get_local_subnets(self) -> List[ipaddress.IPv4Network]:
        """Detect local IPv4 subnets attached to non-loopback interfaces."""
        # 1. `ip -4 -o addr show`
        networks: List[ipaddress.IPv4Network] = []
        try:
            out = subprocess.check_output(["ip", "-4", "-o", "addr", "show"], stderr=subprocess.DEVNULL, timeout=2).decode("utf-8")
            networks = _subnets_from_ip_addr(out)
        except (OSError, SubprocessError) as e:
            logger.debug("ip addr show failed: %s", e)

        # 2. Fallback to /proc/net/route if the ip command is unavailable; a bad line keeps what was read before it
        if not networks:
            try:
                with open(_PROC / "net/route", "r", encoding="utf-8") as f:
                    for line in f.readlines()[1:]:
                        net = _route_line_subnet(line)
                        if net is not None:
                            networks.append(net)
            except (OSError, ValueError) as e:
                logger.debug("Reading /proc/net/route failed: %s", e)
        return networks

    def _probe_local_subnets(self) -> None:
        """Actively triggers kernel ARP requests for all IPs in local subnets."""
        # Only sweep subnets with <= 512 hosts (e.g. /24 .. /30) to remain lightweight
        for net in self._get_local_subnets():
            if net.num_addresses <= 512:
                _udp_arp_burst(net)
                _broadcast_ping(net)

        # Allow 0.5s for kernel to receive and record ARP replies
        time.sleep(0.5)

    def _read_arp_table(self) -> List[Dict[str, str]]:
        neighbors: Dict[str, Dict[str, str]] = {}

        # 1. /proc/net/arp
        arp_path = _PROC / "net/arp"
        if arp_path.exists():
            try:
                with open(arp_path, "r", encoding="utf-8") as f:
                    neighbors = _neighbors_from_proc_arp(f.readlines())
            except OSError as e:
                logger.debug("Failed to read /proc/net/arp: %s", e)

        # 2. Supplementary `ip neigh` check (catches any entries not in /proc/net/arp)
        try:
            out = subprocess.check_output(["ip", "-4", "neigh", "show"], stderr=subprocess.DEVNULL, timeout=2).decode("utf-8")
            _apply_ip_neigh(neighbors, out)
        except (OSError, SubprocessError) as e:
            logger.debug("ip neigh show failed: %s", e)

        return list(neighbors.values())

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

# Settings the server may change at runtime, and how each value is taken over
_REMOTE_CONFIG_FIELDS: List[tuple] = [
    ("interval", lambda v: v),
    ("disk_paths", lambda v: v),
    ("enable_temp", lambda v: v),
    ("enable_patch_check", lambda v: v),
    ("enable_scanner_relay", bool),
]


def _sync_device_id(config: AgentConfig, device_id: Any) -> bool:
    """Take over the device ID the server assigned; True when it changed."""
    if not device_id or device_id == config.device_id:
        return False
    logger.info("Updating Device ID to %s", device_id)
    config.device_id = device_id
    return True


def _sync_remote_config(config: AgentConfig, remote_conf: Any) -> bool:
    """Take over the settings in which the server differs from ``config``; True when any did."""
    if not isinstance(remote_conf, dict):
        return False
    changed = False
    for key, convert in _REMOTE_CONFIG_FIELDS:
        if key in remote_conf and getattr(config, key) != remote_conf[key]:
            setattr(config, key, convert(remote_conf[key]))
            changed = True
    return changed


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
            "temperature": ThermalMetrics(),
            "patches": PatchMetrics(),
            "arp_table": ArpNeighborCollector()
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
        # Both steps must run: one response can carry a new device ID and new settings
        id_changed = _sync_device_id(self.config, response.get("device_id"))
        settings_changed = _sync_remote_config(self.config, response.get("config"))

        if id_changed or settings_changed:
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

def _is_agent_process(args: str) -> bool:
    """True for a Python interpreter running gravitylan-agent.py (not an editor or `tail` on its files)."""
    argv = args.split()
    if not argv or not Path(argv[0]).name.startswith("python"):
        return False
    return any(Path(arg).name == f"{AGENT_NAME}.py" for arg in argv[1:])


def cleanup_ghosts() -> None:
    """Kills other running instances of the agent to avoid conflicts."""
    try:
        my_pid = os.getpid()
        output = subprocess.check_output(["ps", "-eo", "pid=,args="]).decode()
    except (OSError, subprocess.SubprocessError):
        return

    for line in output.splitlines():
        try:
            pid_str, args = line.strip().split(None, 1)
            pid = int(pid_str)
        except ValueError:
            continue
        if pid == my_pid or not _is_agent_process(args):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("Cleaned up ghost process %d", pid)
        except OSError:
            continue

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
