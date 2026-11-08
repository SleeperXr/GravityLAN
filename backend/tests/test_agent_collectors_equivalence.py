"""Five agent methods behave exactly as before they were split into steps.

Frozen copies (agent 0.3.12) of the CPU, disk, network and system-info ``collect`` methods and of
``AgentOrchestrator.process_response`` run next to the live agent over seeded random /proc trees, statvfs
results and server responses. Results, exceptions that escape, the state kept for the next report and the
config the agent would save must match.
"""

import importlib.util
import random
import sys
import time as real_time
from pathlib import Path
from types import SimpleNamespace

import pytest

AGENT_PATH = Path(__file__).resolve().parent.parent.parent / "agent" / "gravitylan-agent.py"


@pytest.fixture(scope="module")
def agent():
    spec = importlib.util.spec_from_file_location("gravitylan_agent_collectors", AGENT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- frozen copies (agent 0.3.12) ----------------------------------------------------------

class OldCPU:
    def __init__(self, agent, root_path):
        self.agent = agent
        self.root_path = root_path
        self.prev_idle = 0
        self.prev_total = 0
        self.prev_lxc_time = 0.0
        self.prev_lxc_ns = 0

    def collect(self):
        agent = self.agent
        if agent.is_lxc_container(self.root_path):
            cpu_ns = agent.get_lxc_cpu_usage_ns(self.root_path)
            if cpu_ns is not None:
                now_time = agent.time.time()
                if self.prev_lxc_time == 0.0:
                    self.prev_lxc_time, self.prev_lxc_ns = now_time, cpu_ns
                    return 0.0

                delta_ns = cpu_ns - self.prev_lxc_ns
                delta_time = now_time - self.prev_lxc_time
                self.prev_lxc_time, self.prev_lxc_ns = now_time, cpu_ns

                if delta_time <= 0 or delta_ns < 0:
                    return 0.0

                cpus = agent.get_lxc_cpu_count(self.root_path)
                delta_time_ns = delta_time * 1e9
                pct = (delta_ns / delta_time_ns) * 100.0 / cpus
                return min(100.0, max(0.0, round(pct, 1)))

        try:
            stat_path = Path(self.root_path) / "proc/stat"
            with open(stat_path, encoding="utf-8") as fh:
                parts = fh.readline().split()

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


class OldNetwork:
    def __init__(self, agent, root_path):
        self.agent = agent
        self.root_path = root_path
        self.prev_counters = {}
        self.prev_time = 0.0

    def collect(self):
        current = {}
        try:
            with open(Path(self.root_path) / "proc/net/dev", encoding="utf-8") as fh:
                for line in fh:
                    if ":" not in line:
                        continue
                    iface, data = line.split(":", 1)
                    iface = iface.strip()
                    if iface == "lo":
                        continue
                    parts = data.split()
                    if len(parts) >= 9:
                        current[iface] = (int(parts[0]), int(parts[8]))
        except (OSError, ValueError):
            return {}

        now = self.agent.time.monotonic()
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


def old_disk(agent, config):
    is_default = len(config.disk_paths) == 1 and config.disk_paths[0] == "/"
    targets = set(config.disk_paths)

    zfs_stats = agent._collect_zfs_stats()

    if is_default:
        targets = agent._discover_mount_targets(list(targets))

    results = []
    seen_devices = set()

    for path in sorted(list(targets)):
        try:
            if path in zfs_stats:
                z = zfs_stats[path]
                total = z["used"] + z["avail"]
                used = z["used"]
            else:
                st = agent.os.statvfs(path)
                fs_id = f"{st.f_blocks}-{st.f_files}"
                if fs_id in seen_devices and path != "/":
                    continue
                seen_devices.add(fs_id)
                total = st.f_blocks * st.f_frsize
                used = total - (st.f_bavail * st.f_frsize)

            if total == 0:
                continue

            results.append({
                "path": path,
                "total_gb": round(total / (1024**3), 1),
                "used_gb": round(used / (1024**3), 1),
                "percent": round(used / total * 100, 1),
            })
        except (OSError, PermissionError):
            continue

    return results


def old_system_info(agent):
    info = {
        "hostname": agent.socket.gethostname(),
        "os": f"{agent.platform.system()} {agent.platform.release()}",
        "arch": agent.platform.machine(),
        "kernel": agent.platform.release(),
    }
    try:
        release = {}
        for line in agent.Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                release[key.strip()] = value.strip().strip('"').strip("'")
        if release:
            pretty = release.get("PRETTY_NAME") or ""
            fallback = f"{release.get('NAME', '')} {release.get('VERSION_ID', '')}".strip()
            info["os"] = pretty or fallback or info["os"]
            info["os_name"] = release.get("NAME") or agent.platform.system()
            info["os_version"] = release.get("VERSION_ID") or agent.platform.release()
            if release.get("VERSION_CODENAME"):
                info["os_codename"] = release["VERSION_CODENAME"]
    except (OSError, UnicodeDecodeError):
        pass
    return info


OLD_REMOTE_FIELDS = (
    ("interval", lambda v: v),
    ("disk_paths", lambda v: v),
    ("enable_temp", lambda v: v),
    ("enable_patch_check", lambda v: v),
    ("enable_scanner_relay", bool),
)


def old_process_response(config, response):
    changed = False

    if response.get("device_id") and response["device_id"] != config.device_id:
        config.device_id = response["device_id"]
        changed = True

    remote_conf = response.get("config")
    if remote_conf and isinstance(remote_conf, dict):
        for key, convert in OLD_REMOTE_FIELDS:
            if key in remote_conf and getattr(config, key) != remote_conf[key]:
                setattr(config, key, convert(remote_conf[key]))
                changed = True

    if changed:
        config.save()


# --- helpers ---------------------------------------------------------------------------------

def _outcome(call):
    """What a call did: its result, or the type of the exception it let out."""
    try:
        return "returned", call()
    except Exception as exc:
        return "raised", type(exc)


def _write(root, rel, content):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")


def _remove(root, rel):
    (root / rel).unlink(missing_ok=True)


def _fake_clock(agent, monkeypatch, start):
    """The agent's wall clock and monotonic clock, both reading clock[0]."""
    clock = [start]
    fake = SimpleNamespace(time=lambda: clock[0], monotonic=lambda: clock[0], sleep=real_time.sleep)
    monkeypatch.setattr(agent, "time", fake)
    return clock


# --- CPU ---------------------------------------------------------------------------------------

STAT_JUNK = ["", "cpu", "cpu  1 2 3", "cpu  a b c d e f g h", "intr 1 2 3 4 5 6 7 8 9\n"]
V2_USAGE = "sys/fs/cgroup/cpu.stat"
V1_USAGE = "sys/fs/cgroup/cpuacct/cpuacct.usage"


def _cpu_host_step(rnd, root, counters):
    roll = rnd.random()
    if roll < 0.1:
        _write(root, "proc/stat", rnd.choice(STAT_JUNK))
    elif roll < 0.2:
        _remove(root, "proc/stat")
    elif roll < 0.8:
        low = -50 if rnd.random() < 0.1 else 0
        counters[:] = [c + rnd.randint(low, 400) for c in counters]
        _write(root, "proc/stat", "cpu  " + " ".join(map(str, counters)) + "\n")
    # otherwise the file stays as it is: nothing moved since the last report


def _cpu_cgroup_step(rnd, root, usage):
    usage[0] += rnd.randint(-1000 if rnd.random() < 0.1 else 0, 3_000_000)
    roll = rnd.random()
    if roll < 0.5:
        _remove(root, V1_USAGE)
        _write(root, V2_USAGE, f"nr_periods 0\nusage_usec {usage[0]}\n")
    elif roll < 0.7:
        _remove(root, V2_USAGE)
        _write(root, V1_USAGE, str(usage[0] * 1000))
    elif roll < 0.8:
        _remove(root, V1_USAGE)
        _write(root, V2_USAGE, "usage_usec broken\n")
    else:
        _remove(root, V1_USAGE)
        _remove(root, V2_USAGE)


@pytest.mark.parametrize("seed", range(200))
def test_cpu_collect_matches(agent, tmp_path, monkeypatch, seed):
    rnd = random.Random(seed)
    clock = _fake_clock(agent, monkeypatch, rnd.choice([0.0, 1000.0]))
    monkeypatch.setattr(agent.os, "cpu_count", lambda: 4)
    if rnd.random() < 0.7:
        _write(tmp_path, "proc/self/cgroup", "0::/lxc/101/ns\n")
    _write(tmp_path, "sys/fs/cgroup/cpu.max", rnd.choice(["200000 100000", "max 100000", "0 100000", "x y"]))

    live = agent.CPUMetrics(root_path=str(tmp_path))
    frozen = OldCPU(agent, str(tmp_path))
    counters = [rnd.randint(1, 10_000) for _ in range(8)]
    usage = [rnd.randint(1, 10**7)]

    for _ in range(6):
        _cpu_host_step(rnd, tmp_path, counters)
        _cpu_cgroup_step(rnd, tmp_path, usage)
        clock[0] += rnd.choice([0.0, -1.0, 1.0, 30.0])
        assert _outcome(lambda: live.collect(SimpleNamespace())) == _outcome(frozen.collect)
        for attr in ("prev_idle", "prev_total", "prev_lxc_time", "prev_lxc_ns"):
            assert getattr(live, attr) == getattr(frozen, attr), attr


# --- network -----------------------------------------------------------------------------------

def _net_dev(rnd):
    rows = ["Inter-|   Receive    |  Transmit\n", " face |bytes packets |bytes packets\n"]
    for iface in rnd.sample(("eth0", "eth1", "br0", "lo"), k=rnd.randint(0, 4)):
        rx, tx = rnd.randint(0, 10**9), rnd.randint(0, 10**9)
        rows.append(f"  {iface}: {rx} 10 0 0 0 0 0 0 {tx} 20 0 0 0 0 0 0\n")
    if rnd.random() < 0.2:
        rows.append("  short: 1 2 3\n")
    if rnd.random() < 0.2:
        rows.append("no colon here\n")
    if rnd.random() < 0.1:
        rows.append("  bad: x 0 0 0 0 0 0 0 9 0 0 0 0 0 0 0\n")
    return "".join(rows)


@pytest.mark.parametrize("seed", range(200))
def test_network_collect_matches(agent, tmp_path, monkeypatch, seed):
    rnd = random.Random(seed)
    clock = _fake_clock(agent, monkeypatch, rnd.choice([0.0, 5000.0]))
    live = agent.NetworkMetrics(root_path=str(tmp_path))
    frozen = OldNetwork(agent, str(tmp_path))

    for _ in range(6):
        roll = rnd.random()
        if roll < 0.1:
            _remove(tmp_path, "proc/net/dev")
        elif roll < 0.2:
            _write(tmp_path, "proc/net/dev", b"\xff\xfe eth0: 1\n")
        else:
            _write(tmp_path, "proc/net/dev", _net_dev(rnd))
        clock[0] += rnd.choice([0.0, -2.0, 1.0, 30.0])

        assert _outcome(lambda: live.collect(SimpleNamespace())) == _outcome(frozen.collect)
        assert live.prev_counters == frozen.prev_counters
        assert live.prev_time == frozen.prev_time


# --- disk --------------------------------------------------------------------------------------

DISK_PATHS = (".", "/", "/data", "/mnt/a", "/mnt/b", "/tank")
FILESYSTEMS = (
    SimpleNamespace(f_blocks=0, f_files=0, f_frsize=4096, f_bavail=0),
    SimpleNamespace(f_blocks=2_621_440, f_files=1000, f_frsize=4096, f_bavail=2_097_152),
    SimpleNamespace(f_blocks=2_621_440, f_files=1000, f_frsize=512, f_bavail=1000),  # same id as the one before
    SimpleNamespace(f_blocks=5_242_880, f_files=7, f_frsize=4096, f_bavail=0),
    PermissionError("denied"),
    OSError("gone"),
    ValueError("not caught by the collector"),
)


@pytest.mark.parametrize("seed", range(300))
def test_disk_collect_matches(agent, monkeypatch, seed):
    rnd = random.Random(seed)
    vfs = {path: rnd.choice(FILESYSTEMS) for path in DISK_PATHS}
    zfs = {
        path: {"used": rnd.choice([0, 2 * 1024**3]), "avail": rnd.choice([0, 5 * 1024**3]), "refer": 0}
        for path in rnd.sample(DISK_PATHS, k=rnd.randint(0, 3))
    }
    discovered = set(rnd.sample(DISK_PATHS, k=rnd.randint(0, 4)))
    disk_paths = rnd.choice([["/"], ["/"], ["/", "/"], [], rnd.sample(DISK_PATHS, k=rnd.randint(1, 5))])
    calls = []

    def statvfs(path):
        calls.append(("statvfs", path))
        found = vfs[path]
        if isinstance(found, Exception):
            raise found
        return found

    def zfs_stats():
        calls.append(("zfs", None))
        return dict(zfs)

    def discover(default_paths):
        calls.append(("discover", list(default_paths)))
        return set(default_paths) | discovered

    monkeypatch.setattr(agent, "os", SimpleNamespace(statvfs=statvfs))
    monkeypatch.setattr(agent, "_collect_zfs_stats", zfs_stats)
    monkeypatch.setattr(agent, "_discover_mount_targets", discover)
    config = SimpleNamespace(disk_paths=disk_paths)

    live = _outcome(lambda: agent.DiskMetrics().collect(config))
    live_calls = list(calls)
    calls.clear()
    assert live == _outcome(lambda: old_disk(agent, config))
    assert live_calls == calls


# --- system info -------------------------------------------------------------------------------

RELEASE_LINES = (
    'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"', "PRETTY_NAME=''", 'PRETTY_NAME=""', "PRETTY_NAME=Alpine",
    'NAME="Debian GNU/Linux"', "NAME=", "NAME='Fedora'",
    'VERSION_ID="12"', "VERSION_ID=", "  VERSION_ID = '40' ",
    "VERSION_CODENAME=bookworm", "VERSION_CODENAME=",
    "# comment", "# a=b", "", "NOEQUALS", "=empty", "ID=debian",
)


def _fake_os_release(agent, monkeypatch, read):
    monkeypatch.setattr(agent, "Path", lambda _path: SimpleNamespace(read_text=lambda encoding: read()))


def _assert_system_info_matches(agent):
    live = _outcome(lambda: agent.SystemInfoProvider().collect(SimpleNamespace()))
    frozen = _outcome(lambda: old_system_info(agent))
    assert live == frozen
    if live[0] == "returned":
        assert list(live[1]) == list(frozen[1])  # the payload keeps its key order


@pytest.mark.parametrize("seed", range(200))
def test_system_info_matches(agent, monkeypatch, seed):
    rnd = random.Random(seed)
    text = "\n".join(rnd.sample(RELEASE_LINES, k=rnd.randint(0, len(RELEASE_LINES))))
    _fake_os_release(agent, monkeypatch, lambda: text)
    _assert_system_info_matches(agent)


@pytest.mark.parametrize("error", [
    FileNotFoundError("gone"),
    PermissionError("denied"),
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
    RuntimeError("not caught by the collector"),
])
def test_system_info_read_failures_match(agent, monkeypatch, error):
    def read():
        raise error

    _fake_os_release(agent, monkeypatch, read)
    _assert_system_info_matches(agent)


# --- server feedback ---------------------------------------------------------------------------

FEEDBACK_FIELDS = ("device_id", "interval", "disk_paths", "enable_temp", "enable_patch_check", "enable_scanner_relay")


def _feedback_config(saves):
    config = SimpleNamespace(device_id=3, interval=30, disk_paths=["/"], enable_temp=True, enable_patch_check=True,
                             enable_scanner_relay=False)
    config.save = lambda: saves.append({key: getattr(config, key) for key in FEEDBACK_FIELDS})
    return config


def _remote_config(rnd):
    options = {
        "interval": [30, 60],
        "disk_paths": [["/"], ["/", "/data"]],
        "enable_temp": [True, False],
        "enable_patch_check": [True, False],
        "enable_scanner_relay": [True, False, 0, 1, "yes", ""],
        "unknown": [1],
    }
    return {key: rnd.choice(values) for key, values in options.items() if rnd.random() < 0.5}


@pytest.mark.parametrize("seed", range(300))
def test_process_response_matches(agent, seed):
    rnd = random.Random(seed)
    response = {}
    if rnd.random() < 0.7:
        response["device_id"] = rnd.choice([0, None, "", 3, 7, "7"])
    if rnd.random() < 0.8:
        response["config"] = _remote_config(rnd) if rnd.random() < 0.7 else rnd.choice([None, {}, [], [1], "nope", 5])

    live_saves, frozen_saves = [], []
    live, frozen = _feedback_config(live_saves), _feedback_config(frozen_saves)

    # Called unbound like the 0.3.12 equivalence test: everything it needs must come from ``config``
    agent.AgentOrchestrator.process_response(SimpleNamespace(config=live), dict(response))
    old_process_response(frozen, dict(response))

    assert live_saves == frozen_saves
    for key in FEEDBACK_FIELDS:
        assert getattr(live, key) == getattr(frozen, key), key
