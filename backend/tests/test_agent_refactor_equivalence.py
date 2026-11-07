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

def old_is_lxc(root_path):
    try:
        p = Path(root_path) / "run/systemd/container"
        if p.exists():
            return p.read_text(encoding="utf-8").strip() == "lxc"
    except Exception:
        pass
    try:
        p = Path(root_path) / "proc/self/cgroup"
        if p.exists():
            content = p.read_text(encoding="utf-8")
            if "lxc" in content or "/lxc/" in content:
                return True
    except Exception:
        pass
    try:
        p = Path(root_path) / "proc/1/environ"
        if p.exists():
            for item in p.read_bytes().split(b"\x00"):
                if item.startswith(b"container=lxc"):
                    return True
    except Exception:
        pass
    return False


def old_cpu_count(root_path, host_count):
    v2 = Path(root_path) / "sys/fs/cgroup/cpu.max"
    if v2.exists():
        try:
            parts = v2.read_text(encoding="utf-8").strip().split()
            if len(parts) == 2 and parts[0] != "max":
                limit, period = int(parts[0]), int(parts[1])
                if period > 0:
                    return limit / period
        except Exception:
            pass
    q = Path(root_path) / "sys/fs/cgroup/cpu/cpu.cfs_quota_us"
    pp = Path(root_path) / "sys/fs/cgroup/cpu/cpu.cfs_period_us"
    if q.exists() and pp.exists():
        try:
            quota, period = int(q.read_text(encoding="utf-8").strip()), int(pp.read_text(encoding="utf-8").strip())
            if quota > 0 and period > 0:
                return quota / period
        except Exception:
            pass
    return host_count or 1.0


def old_memory(root_path):
    used = total = None
    cur, mx = Path(root_path) / "sys/fs/cgroup/memory.current", Path(root_path) / "sys/fs/cgroup/memory.max"
    if cur.exists():
        try:
            used = int(cur.read_text(encoding="utf-8").strip())
            if mx.exists():
                s = mx.read_text(encoding="utf-8").strip()
                if s != "max":
                    total = int(s)
        except Exception:
            pass
    if used is None:
        cur = Path(root_path) / "sys/fs/cgroup/memory/memory.usage_in_bytes"
        mx = Path(root_path) / "sys/fs/cgroup/memory/memory.limit_in_bytes"
        if cur.exists():
            try:
                used = int(cur.read_text(encoding="utf-8").strip())
                if mx.exists():
                    v = int(mx.read_text(encoding="utf-8").strip())
                    if v < 2**60:
                        total = v
            except Exception:
                pass
    return used, total


def old_dnf(out, out_sec, fail):
    result = {}
    try:
        if fail:
            raise OSError("dnf missing")
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        result["patch_available"] = sum(1 for l in lines if len(l.split()) >= 3 and not l.startswith("Last metadata"))
        result["patch_security"] = sum(1 for l in out_sec.splitlines() if l.strip() and not l.startswith("Last metadata"))
    except Exception:
        pass
    return result


def old_yum(out, fail):
    result = {}
    try:
        if fail:
            raise OSError("yum missing")
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        result["patch_available"] = sum(1 for l in lines if len(l.split()) >= 3)
    except Exception:
        pass
    return result


def old_subnets(ip_out, route_text):
    networks = []
    try:
        if ip_out is None:
            raise OSError("no ip")
        for line in ip_out.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[2] == "inet" and not parts[3].startswith("127."):
                try:
                    net = ipaddress.ip_network(parts[3], strict=False)
                    if 16 <= net.prefixlen <= 30:
                        networks.append(net)
                except ValueError:
                    pass
    except Exception:
        pass
    if not networks:
        try:
            if route_text is None:
                raise OSError("no route table")
            for line in route_text.splitlines(keepends=True)[1:]:
                parts = line.strip().split()
                if len(parts) >= 8 and parts[0] != "lo":
                    flags = int(parts[3], 16)
                    if (flags & 0x1) and parts[1] != "00000000":
                        d = socket.inet_ntoa(bytes.fromhex(parts[1])[::-1])
                        m = socket.inet_ntoa(bytes.fromhex(parts[7])[::-1])
                        net = ipaddress.ip_network(f"{d}/{m}", strict=False)
                        if 16 <= net.prefixlen <= 30:
                            networks.append(net)
        except Exception:
            pass
    return networks


def old_arp(arp_text, neigh_out):
    neighbors = {}
    if arp_text is not None:
        for line in arp_text.splitlines(keepends=True)[1:]:
            parts = line.split()
            if len(parts) >= 6:
                ip, flags, mac, dev = parts[0], parts[2], parts[3].lower(), parts[5]
                if flags == "0x2" and mac and mac != "00:00:00:00:00:00":
                    neighbors[ip] = {"ip": ip, "mac": mac, "interface": dev}
    if neigh_out is not None:
        for line in neigh_out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and "lladdr" in parts:
                idx = parts.index("lladdr")
                if idx + 1 < len(parts):
                    ip, mac = parts[0], parts[idx + 1].lower()
                    dev = parts[parts.index("dev") + 1] if "dev" in parts else ""
                    if parts[-1].upper() in ("STALE", "FAILED", "INCOMPLETE"):
                        neighbors.pop(ip, None)
                    elif mac != "00:00:00:00:00:00":
                        neighbors[ip] = {"ip": ip, "mac": mac, "interface": dev}
    return list(neighbors.values())


def old_feedback(config, response):
    changed = False
    if response.get("device_id") and response["device_id"] != config.device_id:
        config.device_id = response["device_id"]
        changed = True
    rc = response.get("config")
    if rc and isinstance(rc, dict):
        for key in ("interval", "disk_paths", "enable_temp", "enable_patch_check"):
            if key in rc and getattr(config, key) != rc[key]:
                setattr(config, key, rc[key])
                changed = True
        if "enable_scanner_relay" in rc and config.enable_scanner_relay != rc["enable_scanner_relay"]:
            config.enable_scanner_relay = bool(rc["enable_scanner_relay"])
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
