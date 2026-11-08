"""The agent behaves exactly as before its 0.3.12 refactor.

Frozen copies (agent 0.3.11) of the LXC/cgroup readers, the dnf/yum counters, the subnet and ARP readers and
the server-feedback handling run next to the live agent over seeded random /proc and /sys trees and command
outputs. Results and the config the agent would save must match.
"""

import importlib.util
import ipaddress
import random
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

AGENT_PATH = Path(__file__).resolve().parent.parent.parent / "agent" / "gravitylan-agent.py"


@pytest.fixture(scope="module")
def agent():
    spec = importlib.util.spec_from_file_location("gravitylan_agent_equivalence", AGENT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- frozen copies (agent 0.3.11) ----------------------------------------------------------

_OLD_ERRORS = (OSError, ValueError, UnicodeDecodeError)


def _old_read_text(root_path, rel):
    p = Path(root_path) / rel
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except _OLD_ERRORS:
        return None


def _old_pid1_has_lxc_env(root_path):
    p = Path(root_path) / "proc/1/environ"
    if not p.exists():
        return False
    try:
        return any(item.startswith(b"container=lxc") for item in p.read_bytes().split(b"\x00"))
    except _OLD_ERRORS:
        return False


def old_is_lxc(root_path):
    marker = _old_read_text(root_path, "run/systemd/container")
    if marker is not None:
        return marker.strip() == "lxc"
    cgroup = _old_read_text(root_path, "proc/self/cgroup")
    if cgroup is not None and ("lxc" in cgroup or "/lxc/" in cgroup):
        return True
    return _old_pid1_has_lxc_env(root_path)


def _old_cpu_v2(root_path):
    text = _old_read_text(root_path, "sys/fs/cgroup/cpu.max")
    parts = text.strip().split() if text is not None else []
    if len(parts) != 2 or parts[0] == "max":
        return None
    try:
        limit, period = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    return limit / period if period > 0 else None


def _old_cpu_v1(root_path):
    q_text = _old_read_text(root_path, "sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    p_text = _old_read_text(root_path, "sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if q_text is None or p_text is None:
        return None
    try:
        quota, period = int(q_text.strip()), int(p_text.strip())
    except ValueError:
        return None
    return quota / period if quota > 0 and period > 0 else None


def old_cpu_count(root_path, host_count):
    limit = _old_cpu_v2(root_path) or _old_cpu_v1(root_path)
    return limit if limit is not None else (host_count or 1.0)


def _old_mem_limit_v2(text):
    s = text.strip()
    return None if s == "max" else int(s)


def _old_mem_limit_v1(text):
    v = int(text.strip())
    return v if v < 2**60 else None


def _old_cgroup_mem(root_path, cur_rel, mx_rel, parse_limit):
    cur_text = _old_read_text(root_path, cur_rel)
    if cur_text is None:
        return None, None
    used = total = None
    try:
        used = int(cur_text.strip())
        mx_text = _old_read_text(root_path, mx_rel)
        if mx_text is not None:
            total = parse_limit(mx_text)
    except ValueError:
        return used, total
    return used, total


def old_memory(root_path):
    used, total = _old_cgroup_mem(root_path, "sys/fs/cgroup/memory.current", "sys/fs/cgroup/memory.max", _old_mem_limit_v2)
    if used is None:
        used, total = _old_cgroup_mem(
            root_path, "sys/fs/cgroup/memory/memory.usage_in_bytes", "sys/fs/cgroup/memory/memory.limit_in_bytes", _old_mem_limit_v1
        )
    return used, total


def old_dnf(out, out_sec, fail):
    if fail:
        return {}
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    return {
        "patch_available": sum(1 for l in lines if len(l.split()) >= 3 and not l.startswith("Last metadata")),
        "patch_security": sum(1 for l in out_sec.splitlines() if l.strip() and not l.startswith("Last metadata")),
    }


def old_yum(out, fail):
    if fail:
        return {}
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    return {"patch_available": sum(1 for l in lines if len(l.split()) >= 3)}


def _old_addr_subnet(line):
    parts = line.split()
    if len(parts) < 4 or parts[2] != "inet" or parts[3].startswith("127."):
        return None
    try:
        net = ipaddress.ip_network(parts[3], strict=False)
    except ValueError:
        return None
    return net if 16 <= net.prefixlen <= 30 else None


def _old_route_subnet(line):
    parts = line.strip().split()
    if len(parts) < 8 or parts[0] == "lo":
        return None
    if not (int(parts[3], 16) & 0x1) or parts[1] == "00000000":
        return None
    d = socket.inet_ntoa(bytes.fromhex(parts[1])[::-1])
    m = socket.inet_ntoa(bytes.fromhex(parts[7])[::-1])
    net = ipaddress.ip_network(f"{d}/{m}", strict=False)
    return net if 16 <= net.prefixlen <= 30 else None


def old_subnets(ip_out, route_text):
    networks = []
    if ip_out is not None:
        for line in ip_out.splitlines():
            net = _old_addr_subnet(line)
            if net is not None:
                networks.append(net)
    if not networks and route_text is not None:
        try:
            for line in route_text.splitlines(keepends=True)[1:]:
                net = _old_route_subnet(line)
                if net is not None:
                    networks.append(net)
        except _OLD_ERRORS:
            return networks
    return networks


def _old_arp_proc_line(neighbors, line):
    parts = line.split()
    if len(parts) < 6:
        return
    ip, flags, mac, dev = parts[0], parts[2], parts[3].lower(), parts[5]
    if flags == "0x2" and mac and mac != "00:00:00:00:00:00":
        neighbors[ip] = {"ip": ip, "mac": mac, "interface": dev}


def _old_arp_neigh_line(neighbors, line):
    parts = line.split()
    if len(parts) < 5 or "lladdr" not in parts:
        return
    idx = parts.index("lladdr")
    if idx + 1 >= len(parts):
        return
    ip, mac = parts[0], parts[idx + 1].lower()
    dev = parts[parts.index("dev") + 1] if "dev" in parts else ""
    if parts[-1].upper() in ("STALE", "FAILED", "INCOMPLETE"):
        neighbors.pop(ip, None)
    elif mac != "00:00:00:00:00:00":
        neighbors[ip] = {"ip": ip, "mac": mac, "interface": dev}


def old_arp(arp_text, neigh_out):
    neighbors = {}
    if arp_text is not None:
        for line in arp_text.splitlines(keepends=True)[1:]:
            _old_arp_proc_line(neighbors, line)
    if neigh_out is not None:
        for line in neigh_out.splitlines():
            _old_arp_neigh_line(neighbors, line)
    return list(neighbors.values())


_OLD_FEEDBACK_FIELDS = (
    ("interval", lambda v: v),
    ("disk_paths", lambda v: v),
    ("enable_temp", lambda v: v),
    ("enable_patch_check", lambda v: v),
    ("enable_scanner_relay", bool),
)


def _old_sync_rc(config, rc):
    if not isinstance(rc, dict):
        return False
    changed = False
    for key, convert in _OLD_FEEDBACK_FIELDS:
        if key in rc and getattr(config, key) != rc[key]:
            setattr(config, key, convert(rc[key]))
            changed = True
    return changed


def old_feedback(config, response):
    changed = False
    if response.get("device_id") and response["device_id"] != config.device_id:
        config.device_id = response["device_id"]
        changed = True
    if _old_sync_rc(config, response.get("config")):
        changed = True
    return changed


# --- random trees ----------------------------------------------------------------------------

def _write(root, rel, content):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")


def _tree(rnd, root):
    pick = rnd.choice
    if rnd.random() < 0.4:
        _write(root, "run/systemd/container", pick(["lxc\n", "docker", "", "  lxc  "]))
    if rnd.random() < 0.5:
        _write(root, "proc/self/cgroup", pick(["0::/lxc/101/ns\n", "0::/user.slice\n", "12:cpu:/lxc.payload.ct", ""]))
    if rnd.random() < 0.5:
        _write(root, "proc/1/environ", pick([b"PATH=/bin\x00container=lxc\x00", b"container=docker\x00", b"", b"\xff\xfe"]))
    if rnd.random() < 0.5:
        _write(root, "sys/fs/cgroup/cpu.max", pick(["200000 100000", "max 100000", "50000 0", "x y", "150000", ""]))
    if rnd.random() < 0.5:
        _write(root, "sys/fs/cgroup/cpu/cpu.cfs_quota_us", pick(["-1", "200000", "abc", "0"]))
        if rnd.random() < 0.8:
            _write(root, "sys/fs/cgroup/cpu/cpu.cfs_period_us", pick(["100000", "0", "x"]))
    if rnd.random() < 0.5:
        _write(root, "sys/fs/cgroup/memory.current", pick(["104857600", "x", ""]))
        if rnd.random() < 0.7:
            _write(root, "sys/fs/cgroup/memory.max", pick(["max", "2147483648", "bad"]))
    if rnd.random() < 0.5:
        _write(root, "sys/fs/cgroup/memory/memory.usage_in_bytes", pick(["52428800", "oops"]))
        if rnd.random() < 0.7:
            _write(root, "sys/fs/cgroup/memory/memory.limit_in_bytes", pick(["9223372036854771712", "1073741824", "n/a"]))


@pytest.mark.parametrize("seed", range(300))
def test_cgroup_and_lxc_readers_match(agent, tmp_path, seed, monkeypatch):
    rnd = random.Random(seed)
    root = tmp_path / f"r{seed}"
    root.mkdir()
    _tree(rnd, root)
    monkeypatch.setattr(agent.os, "cpu_count", lambda: 6)
    assert agent.is_lxc_container(str(root)) == old_is_lxc(str(root))
    assert agent.get_lxc_cpu_count(str(root)) == old_cpu_count(str(root), 6)
    ram = agent.RAMMetrics(root_path=str(root))
    assert ram._lxc_memory_limits() == old_memory(str(root))


DNF_OUT = ["", "Last metadata expiration check: 0:01 ago\n\ncurl.x86_64  7.8  updates\nbad line\n  zlib.x86_64 1.3 base\n",
           "a b c\nd e\n\n   \nLast metadata x y z\n"]
SEC_OUT = ["", "FEDORA-2026-1 Important/Sec. curl\nLast metadata expiration\n  \nFEDORA-2026-2 Low zlib\n"]


@pytest.mark.parametrize(("out", "sec", "fail"), [(o, s, f) for o in DNF_OUT for s in SEC_OUT for f in (False, True)])
def test_dnf_and_yum_counts_match(agent, monkeypatch, out, sec, fail):
    def fake_run(cmd, **_kw):
        if fail:
            raise OSError("missing")
        text = sec if "updateinfo" in cmd else out
        return SimpleNamespace(stdout=text.encode(), returncode=0)

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    monkeypatch.setattr(agent.shutil, "which", lambda name: None)
    patches = agent.PatchMetrics()
    result = {}
    patches._collect_dnf(result)
    assert result == old_dnf(out, sec, fail)
    result = {}
    patches._collect_yum(result)
    assert result == old_yum(out, fail)


IP_OUT = [
    None, "",
    "1: lo    inet 127.0.0.1/8 scope host lo\n2: eth0    inet 192.168.1.20/24 brd 192.168.1.255 scope global eth0\n"
    "3: br0 inet 10.0.0.1/8 scope global br0\n4: wg0 inet 10.9.0.1/32 scope global wg0\n5: x inet bad/99\n6: y inet6 fe80::1/64\n",
    "2: eth1    inet 172.16.5.10/16 scope global eth1\n",
]
ROUTE = [
    None,
    "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
    "eth0\t0001A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\n"
    "eth0\t00000000\t0101A8C0\t0003\t0\t0\t0\t00000000\n"
    "lo\t0000007F\t00000000\t0001\t0\t0\t0\t000000FF\n"
    "eth1\t000010AC\t00000000\t0000\t0\t0\t0\t0000FFFF\n"
    "eth2\t00000A0A\t00000000\t0001\t0\t0\t0\t00FFFFFF\n",
    "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
    "eth0\t0001A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\n"
    "eth0\tZZ\t00000000\t0001\t0\t0\t0\t00FFFFFF\n"
    "eth1\t000010AC\t00000000\t0001\t0\t0\t0\t0000FFFF\n",
]


def _fake_subprocess(agent, outputs):
    def check_output(cmd, **_kw):
        text = outputs.get(cmd[2] if cmd[1] == "-4" else cmd[1])
        if text is None:
            raise OSError("missing")
        return text.encode()

    return SimpleNamespace(check_output=check_output, run=agent.subprocess.run, DEVNULL=-3, PIPE=-1)


@pytest.mark.parametrize(("ip_out", "route"), [(i, r) for i in IP_OUT for r in ROUTE])
def test_subnet_detection_matches(agent, monkeypatch, tmp_path, ip_out, route):
    if route is not None:
        _write(tmp_path, "net/route", route)
    monkeypatch.setattr(agent, "_PROC", tmp_path)
    monkeypatch.setattr(agent, "subprocess", _fake_subprocess(agent, {"-o": ip_out}))
    assert agent.ArpNeighborCollector()._get_local_subnets() == old_subnets(ip_out, route)


ARP = [
    None,
    "IP address       HW type     Flags       HW address            Mask     Device\n"
    "192.168.1.1      0x1         0x2         AA:BB:CC:DD:EE:01     *        eth0\n"
    "192.168.1.9      0x1         0x0         00:00:00:00:00:00     *        eth0\n"
    "192.168.1.7      0x1         0x2         00:00:00:00:00:00     *        eth0\n"
    "192.168.1.5      0x1         0x2         aa:bb:cc:dd:ee:05     *        eth1\n"
    "short line\n",
]
NEIGH = [
    None, "",
    "192.168.1.5 dev eth1 lladdr aa:bb:cc:dd:ee:05 STALE\n192.168.1.30 dev eth0 lladdr AA:BB:CC:00:00:30 REACHABLE\n"
    "192.168.1.31 lladdr aa:bb:cc:00:00:31 x DELAY\n192.168.1.32 dev eth0 lladdr\n192.168.1.33 dev eth0 FAILED\n"
    "192.168.1.1 dev eth0 lladdr 00:00:00:00:00:00 PERMANENT\n",
]


@pytest.mark.parametrize(("arp", "neigh"), [(a, n) for a in ARP for n in NEIGH])
def test_arp_table_matches(agent, monkeypatch, tmp_path, arp, neigh):
    if arp is not None:
        _write(tmp_path, "net/arp", arp)
    monkeypatch.setattr(agent, "_PROC", tmp_path)
    monkeypatch.setattr(agent, "subprocess", _fake_subprocess(agent, {"neigh": neigh}))
    assert agent.ArpNeighborCollector()._read_arp_table() == old_arp(arp, neigh)


RESPONSES = [
    {}, {"device_id": 7}, {"device_id": 3}, {"config": None}, {"config": "nope"},
    {"config": {"interval": 30, "enable_temp": True}},
    {"config": {"interval": 60, "disk_paths": ["/", "/data"], "enable_temp": False, "enable_patch_check": False}},
    {"config": {"enable_scanner_relay": 1}}, {"config": {"enable_scanner_relay": 0}},
    {"device_id": 9, "config": {"enable_scanner_relay": "yes", "unknown": 1}},
]


@pytest.mark.parametrize("response", RESPONSES)
def test_server_feedback_matches(agent, monkeypatch, response):
    def config():
        return SimpleNamespace(device_id=3, interval=30, disk_paths=["/"], enable_temp=True, enable_patch_check=True,
                               enable_scanner_relay=False, saved=0, save=None)

    live, frozen = config(), config()
    live.save = lambda: setattr(live, "saved", live.saved + 1)
    orchestrator = SimpleNamespace(config=live)
    agent.AgentOrchestrator.process_response(orchestrator, dict(response))
    changed = old_feedback(frozen, dict(response))
    assert live.saved == (1 if changed else 0)
    for key in ("device_id", "interval", "disk_paths", "enable_temp", "enable_patch_check", "enable_scanner_relay"):
        assert getattr(live, key) == getattr(frozen, key), key
