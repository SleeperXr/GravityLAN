"""Tests for the pure/query logic in the agent API (app/api/agent.py).

Focuses on behavior-preserving coverage of helper functions and the
server-URL detection that is shared by config download, install script,
and deploy endpoints.
"""

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

import app.api.agent as agent_module


def _make_subnet(ip, iface):
    """Build a minimal object exposing the fields _pick_best_subnet reads."""
    return SimpleNamespace(ip_address=ip, interface_name=iface)


# --- _pick_best_subnet ------------------------------------------------------

def test_pick_best_subnet_none_for_empty():
    assert agent_module._pick_best_subnet([]) is None
    assert agent_module._pick_best_subnet(None) is None


def test_pick_best_subnet_prefers_physical_private():
    subnets = [
        _make_subnet("172.17.0.1", "docker0"),
        _make_subnet("192.168.1.50", "eth0"),
        _make_subnet("10.0.0.5", "wlan0"),
    ]
    best = agent_module._pick_best_subnet(subnets)
    assert best.ip_address == "192.168.1.50"  # eth0 +100, 192.168 +50
    assert best.interface_name == "eth0"


def test_pick_best_subnet_avoids_docker_bridge():
    subnets = [
        _make_subnet("172.17.0.1", "docker0"),
        _make_subnet("10.0.0.5", "br-abc123"),
    ]
    best = agent_module._pick_best_subnet(subnets)
    # both penalized; 10.x gets +40 so it wins over the docker bridge
    assert best.interface_name == "br-abc123"
    assert best.ip_address == "10.0.0.5"


def test_pick_best_subnet_avoids_tailscale_tun():
    subnets = [
        _make_subnet("100.64.0.1", "tailscale0"),
        _make_subnet("192.168.2.10", "eth0"),
    ]
    best = agent_module._pick_best_subnet(subnets)
    assert best.interface_name == "eth0"


def test_pick_best_subnet_substring_collision_veth_contains_eth():
    # "eth" is a substring of "vethxyz", so it is BOTH preferred (+100) and
    # penalized (-100) plus +40 for the 10.x range -> net +40. This is the
    # original deploy_agent_endpoint scoring, preserved verbatim.
    subnets = [
        _make_subnet("10.0.0.5", "vethxyz"),
        _make_subnet("192.168.2.10", "docker0"),
    ]
    best = agent_module._pick_best_subnet(subnets)
    assert best.interface_name == "vethxyz"
    assert best.ip_address == "10.0.0.5"


# --- _server_url_from_ip ----------------------------------------------------

def test_server_url_from_ip_with_port(monkeypatch):
    monkeypatch.setattr(agent_module.settings, "port", 8000)
    assert agent_module._server_url_from_ip("192.168.1.50") == "http://192.168.1.50:8000"


def test_server_url_from_ip_omits_port_80(monkeypatch):
    monkeypatch.setattr(agent_module.settings, "port", 80)
    assert agent_module._server_url_from_ip("192.168.1.50") == "http://192.168.1.50"


# --- _detect_server_url -----------------------------------------------------

class _FakeSetting:
    def __init__(self, value):
        self.value = value


@pytest.mark.asyncio
async def test_detect_server_url_from_setting(monkeypatch):
    class FakeResult:
        def scalar_one_or_none(self):
            return _FakeSetting("http://gravitylan.example:9000")

    class FakeDB:
        async def execute(self, stmt):
            return FakeResult()

    monkeypatch.setattr("app.scanner.utils.get_local_subnets", None)  # must not be called
    url = await agent_module._detect_server_url(FakeDB())
    assert url == "http://gravitylan.example:9000"


@pytest.mark.asyncio
async def test_detect_server_url_detects_local_ip(monkeypatch):
    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeDB:
        async def execute(self, stmt):
            return FakeResult()

    monkeypatch.setattr("app.scanner.utils.get_local_subnets", lambda: [_make_subnet("192.168.1.50", "eth0")])
    monkeypatch.setattr(agent_module.settings, "port", 8000)

    url = await agent_module._detect_server_url(FakeDB())
    assert url == "http://192.168.1.50:8000"


@pytest.mark.asyncio
async def test_detect_server_url_falls_back_to_localhost(monkeypatch):
    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeDB:
        async def execute(self, stmt):
            return FakeResult()

    monkeypatch.setattr("app.scanner.utils.get_local_subnets", lambda: [])
    monkeypatch.setattr(agent_module.settings, "port", 8000)

    url = await agent_module._detect_server_url(FakeDB())
    assert url == "http://localhost:8000"


@pytest.mark.asyncio
async def test_detect_server_url_localhost_omits_port_80(monkeypatch):
    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeDB:
        async def execute(self, stmt):
            return FakeResult()

    monkeypatch.setattr("app.scanner.utils.get_local_subnets", lambda: [])
    monkeypatch.setattr(agent_module.settings, "port", 80)

    url = await agent_module._detect_server_url(FakeDB())
    assert url == "http://localhost"


# --- _build_update_command --------------------------------------------------

def test_build_update_command_apt():
    cmd = agent_module._build_update_command("apt", "full")
    assert cmd.startswith("DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade")
    sec = agent_module._build_update_command("apt", "security-only")
    assert "install --only-upgrade" in sec


def test_build_update_command_dnf():
    assert agent_module._build_update_command("dnf", "full") == "dnf upgrade -y"
    assert agent_module._build_update_command("dnf", "security-only") == "dnf upgrade --security -y"


def test_build_update_command_yum():
    assert agent_module._build_update_command("yum", "full") == "yum update -y"
    assert agent_module._build_update_command("yum", "security-only") == "yum update --security -y"


def test_build_update_command_unsupported():
    assert agent_module._build_update_command("pacman", "full") is None
    assert agent_module._build_update_command(None, "full") is None


# --- uptime helpers ---------------------------------------------------------

def _fake_token(last_seen=None, created_at=None):
    return SimpleNamespace(last_seen=last_seen, created_at=created_at)


def test_is_agent_active_recent():
    now = datetime.now(timezone.utc)
    token = _fake_token(last_seen=now - timedelta(minutes=1))
    assert agent_module._is_agent_active(token, now) is True


def test_is_agent_active_stale():
    now = datetime.now(timezone.utc)
    token = _fake_token(last_seen=now - timedelta(minutes=10))
    assert agent_module._is_agent_active(token, now) is False


def test_is_agent_active_no_last_seen():
    assert agent_module._is_agent_active(_fake_token(last_seen=None), datetime.now(timezone.utc)) is False


def test_compute_uptime_pct_just_born_no_heartbeats():
    # created == now -> window clamped to 60s -> expected=2 heartbeats -> 0/2 = 0%
    now = datetime.now(timezone.utc)
    token = _fake_token(created_at=now)
    assert agent_module._compute_uptime_pct(token, now, now - timedelta(hours=24), []) == 0.0


def test_compute_uptime_pct_below_100_with_fewer_heartbeats():
    now = datetime.now(timezone.utc)
    created = now - timedelta(hours=1)
    token = _fake_token(created_at=created)
    # expected = 3600/30 = 120; 60 present -> 50%
    assert agent_module._compute_uptime_pct(token, now, now - timedelta(hours=24), list(range(60))) == 50.0


def test_compute_uptime_history_length_24():
    now = datetime.now(timezone.utc)
    token = _fake_token(created_at=now - timedelta(days=1))
    history = agent_module._compute_uptime_history(token, now, now - timedelta(hours=24), [])
    assert len(history) == 24


# --- downsample_metrics edge cases ------------------------------------------

def test_downsample_metrics_empty():
    assert agent_module.downsample_metrics([], "24h") == []


def test_downsample_metrics_buckets_aggregate():
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    m1 = SimpleNamespace(
        timestamp=base,
        cpu_percent=10.0, ram_percent=20.0,
        ram_used_mb=100, ram_total_mb=200, temperature=30.0,
        disk_json='[{"path": "/"}]', net_json='{"eth0": {}}',
    )
    m2 = SimpleNamespace(
        timestamp=base + timedelta(seconds=120),
        cpu_percent=30.0, ram_percent=40.0,
        ram_used_mb=120, ram_total_mb=200, temperature=50.0,
        disk_json=None, net_json=None,
    )
    out = agent_module.downsample_metrics([m1, m2], "6h")  # 300s buckets
    assert len(out) == 1
    assert out[0]["cpu_percent"] == 20.0
    assert out[0]["ram"]["percent"] == 30.0
    assert out[0]["ram"]["used_mb"] == 110
    assert out[0]["temperature"] == 40.0


def test_downsample_metrics_naive_timestamp_ok():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    m = SimpleNamespace(
        timestamp=naive,
        cpu_percent=10.0, ram_percent=20.0,
        ram_used_mb=100, ram_total_mb=200, temperature=None,
        disk_json=None, net_json=None,
    )
    out = agent_module.downsample_metrics([m], "24h")
    assert len(out) == 1
    assert out[0]["temperature"] is None
