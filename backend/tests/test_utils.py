"""Tests for the scanner utility functions (app/scanner/utils.py)."""

from unittest.mock import MagicMock

import pytest

import app.scanner.utils as utils


# --- _is_virtual_interface --------------------------------------------------

def test_is_virtual_keyword_interfaces():
    assert utils._is_virtual_interface("vboxnet0", "192.168.56.1") is True
    assert utils._is_virtual_interface("Tailscale", "100.64.0.1") is True
    assert utils._is_virtual_interface("vEthernet (WSL)", "172.20.0.1") is True
    assert utils._is_virtual_interface("tunnel0", "10.8.0.1") is True
    # 'tun0' alone is not on the keyword list (original behaviour kept)
    assert utils._is_virtual_interface("tun0", "10.8.0.1") is False


def test_is_virtual_docker_bridges():
    assert utils._is_virtual_interface("docker0", "172.17.0.1") is True
    assert utils._is_virtual_interface("br-abc123", "172.18.0.1") is True


def test_is_virtual_172_on_generic_names():
    assert utils._is_virtual_interface("eth0", "172.17.0.2") is True
    assert utils._is_virtual_interface("veth2f3a", "172.19.0.1") is True


def test_is_virtual_physical_interfaces():
    assert utils._is_virtual_interface("eth0", "192.168.1.5") is False
    assert utils._is_virtual_interface("br0", "192.168.1.1") is False
    assert utils._is_virtual_interface("wlan0", "192.168.1.10") is False


# --- _add_subnet ------------------------------------------------------------

def test_add_subnet_skips_loopback_and_link_local():
    subnets = []
    seen = set()
    utils._add_subnet(subnets, seen, "lo", "127.0.0.1", "255.0.0.0")
    utils._add_subnet(subnets, seen, "wlan0", "169.254.12.34", "255.255.0.0")
    utils._add_subnet(subnets, seen, "", "", "255.255.255.0")
    assert subnets == []


def test_add_subnet_deduplicates():
    subnets = []
    seen = set()
    utils._add_subnet(subnets, seen, "eth0", "192.168.1.5", "255.255.255.0")
    utils._add_subnet(subnets, seen, "eth1", "192.168.1.6", "255.255.255.0")
    assert len(subnets) == 1
    assert subnets[0].interface_name == "eth0"


def test_add_subnet_marks_virtual():
    subnets = []
    seen = set()
    utils._add_subnet(subnets, seen, "docker0", "172.17.0.1", "255.255.0.0")
    assert subnets[0].is_virtual is True


def test_add_subnet_invalid_mask_skipped():
    subnets = []
    seen = set()
    utils._add_subnet(subnets, seen, "eth0", "999.999.999.1", "255.255.255.0")
    assert subnets == []


# --- stage collectors -------------------------------------------------------

def test_collect_psutil_subnets(monkeypatch):
    class FakeAddr:
        def __init__(self, ip, netmask, family):
            self.address = ip
            self.netmask = netmask
            self.family = family

    class FakeStats:
        isup = True

    fake_psutil = MagicMock()
    fake_psutil.net_if_addrs.return_value = {
        "eth0": [FakeAddr("192.168.1.5", "255.255.255.0", 2)],
        "lo": [FakeAddr("127.0.0.1", "255.0.0.0", 2)],
    }
    fake_psutil.net_if_stats.return_value = {"eth0": FakeStats(), "lo": FakeStats()}
    monkeypatch.setitem(utils.sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(utils.socket, "AF_INET", 2)

    subnets = []
    seen = set()
    utils._collect_psutil_subnets(subnets, seen)
    assert len(subnets) == 1
    assert subnets[0].subnet == "192.168.1.0/24"


def test_collect_psutil_subnets_handles_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("psutil not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(utils.sys, "platform", "linux")
    subnets = []
    seen = set()
    utils._collect_psutil_subnets(subnets, seen)  # must not raise
    assert subnets == []


# --- _is_usable_psutil_interface ---------------------------------------------

def test_is_usable_psutil_interface_down_skipped():
    class FakeStats:
        isup = False

    stats = {"eth0": FakeStats()}
    assert utils._is_usable_psutil_interface("eth0", stats) is False


def test_is_usable_psutil_interface_loopback_skipped():
    class FakeStats:
        isup = True

    stats = {"lo": FakeStats()}
    assert utils._is_usable_psutil_interface("lo", stats) is False
    assert utils._is_usable_psutil_interface("Loopback Pseudo-Interface", stats) is False


def test_is_usable_psutil_interface_unknown_iface_kept():
    stats = {}
    assert utils._is_usable_psutil_interface("eth0", stats) is True


# --- netifaces collector -----------------------------------------------------

def test_collect_netifaces_subnets(monkeypatch):
    class FakeNetifaces:
        @staticmethod
        def interfaces():
            return ["eth0"]

        @staticmethod
        def ifaddresses(iface):
            return {2: [{"addr": "10.0.0.5", "netmask": "255.255.255.0"}]}

    fake = MagicMock()
    fake.interfaces = FakeNetifaces.interfaces
    fake.ifaddresses = FakeNetifaces.ifaddresses
    fake.AF_INET = 2
    monkeypatch.setitem(utils.sys.modules, "netifaces", fake)

    subnets = []
    seen = set()
    utils._collect_netifaces_subnets(subnets, seen)
    assert len(subnets) == 1
    assert subnets[0].subnet == "10.0.0.0/24"


def test_collect_netifaces_subnets_skips_no_ipv4(monkeypatch):
    class FakeNetifaces:
        @staticmethod
        def interfaces():
            return ["eth0"]

        @staticmethod
        def ifaddresses(iface):
            return {10: [{"addr": "fe80::1"}]}

    fake = MagicMock()
    fake.interfaces = FakeNetifaces.interfaces
    fake.ifaddresses = FakeNetifaces.ifaddresses
    fake.AF_INET = 2
    monkeypatch.setitem(utils.sys.modules, "netifaces", fake)

    subnets = []
    seen = set()
    utils._collect_netifaces_subnets(subnets, seen)
    assert subnets == []


def test_collect_netifaces_subnets_handles_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "netifaces":
            raise ImportError("netifaces not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    subnets = []
    seen = set()
    utils._collect_netifaces_subnets(subnets, seen)  # must not raise
    assert subnets == []


def test_get_local_subnets_fallback_returns_virtual(monkeypatch):
    """When no physical subnet is found, virtual ones must be returned as a fallback."""
    monkeypatch.setattr(utils.sys, "platform", "linux")
    monkeypatch.setattr(utils, "_collect_psutil_subnets", lambda s, v: None)
    monkeypatch.setattr(utils, "_collect_netifaces_subnets", lambda s, v: None)
    monkeypatch.setattr(utils, "_collect_powershell_subnets", lambda s, v: None)

    def fake_socket(monkeypatch, subnets, seen):
        utils._add_subnet(subnets, seen, "docker0", "172.17.0.1", "255.255.0.0")

    monkeypatch.setattr(utils, "_collect_socket_subnets", lambda s, v: fake_socket(monkeypatch, s, v))

    result = utils.get_local_subnets()
    assert len(result) == 1
    assert result[0].is_virtual is True


def test_get_local_subnets_prioritizes_physical(monkeypatch):
    monkeypatch.setattr(utils.sys, "platform", "linux")

    def fake_psutil(subnets, seen):
        utils._add_subnet(subnets, seen, "eth0", "192.168.1.5", "255.255.255.0")

    monkeypatch.setattr(utils, "_collect_psutil_subnets", fake_psutil)
    monkeypatch.setattr(utils, "_collect_netifaces_subnets", lambda s, v: None)
    monkeypatch.setattr(utils, "_collect_powershell_subnets", lambda s, v: None)
    monkeypatch.setattr(utils, "_collect_socket_subnets", lambda s, v: None)

    result = utils.get_local_subnets()
    assert len(result) == 1
    assert result[0].subnet == "192.168.1.0/24"
    assert result[0].is_virtual is False


# --- check_port_async / ping_host_async -------------------------------------

@pytest.mark.asyncio
async def test_check_port_async_open(monkeypatch):
    from unittest.mock import AsyncMock

    async def fake_open_connection(ip, port):
        writer = MagicMock()
        writer.wait_closed = AsyncMock()
        return MagicMock(), writer

    monkeypatch.setattr(utils.asyncio, "open_connection", fake_open_connection)
    assert await utils.check_port_async("192.168.1.1", 80) is True


@pytest.mark.asyncio
async def test_check_port_async_closed(monkeypatch):
    async def fake_open_connection(ip, port):
        raise ConnectionRefusedError()

    monkeypatch.setattr(utils.asyncio, "open_connection", fake_open_connection)
    assert await utils.check_port_async("192.168.1.1", 80) is False
