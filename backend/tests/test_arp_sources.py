"""app/scanner/arp.py beyond the parsers: the Linux and Windows neighbour sources, how the tables are
combined, the active probe for hosts without a MAC, the gateway/proxy-ARP filter edge cases and the
full resolve_mac_addresses path. Commands are faked; nothing is sent on the network."""

import json
import subprocess
from types import SimpleNamespace

import pytest

import app.scanner.arp as arp

LINUX_NEIGH = (
    "192.0.2.1 dev eth0 lladdr aa:bb:cc:00:00:01 REACHABLE\n"
    "192.0.2.7 dev eth0 lladdr aa:bb:cc:00:00:07 STALE\n"
    "192.0.2.8 dev eth0  FAILED\n"
    "fe80::1 dev eth0 lladdr aa:bb:cc:00:00:09 router REACHABLE\n"
)


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(arp.sys, "platform", "linux")


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(arp.sys, "platform", "win32")


# --- neighbour sources ---------------------------------------------------------------------------

def test_linux_stale_ips(linux, monkeypatch):
    monkeypatch.setattr(arp.subprocess, "check_output", lambda *a, **k: LINUX_NEIGH.encode())
    assert arp.get_linux_stale_ips() == {"192.0.2.7", "192.0.2.8"}


def test_linux_stale_ips_on_windows_and_on_errors(windows, monkeypatch):
    assert arp.get_linux_stale_ips() == set()
    monkeypatch.setattr(arp.sys, "platform", "linux")

    def missing(*a, **k):
        raise FileNotFoundError("ip")

    monkeypatch.setattr(arp.subprocess, "check_output", missing)
    assert arp.get_linux_stale_ips() == set()


@pytest.mark.parametrize("line", ["192.0.2.1 dev eth0 lladdr aa:bb:cc:00:00:01 STALE", "192.0.2.1 dev eth0 lladdr"])
def test_extract_neighbor_skips_stale_and_cut_lines(line):
    assert arp._extract_neighbor(line) is None


def test_powershell_neighbours(windows, monkeypatch):
    data = [
        {"IPAddress": "192.0.2.1", "LinkLayerAddress": "AA-BB-CC-00-00-01"},
        {"IPAddress": "192.0.2.2", "LinkLayerAddress": ""},
        {"IPAddress": "fe80::1", "LinkLayerAddress": "00-00"},
    ]
    monkeypatch.setattr(arp.subprocess, "check_output", lambda *a, **k: json.dumps(data).encode("cp850"))
    assert arp.get_powershell_neighbors() == {"192.0.2.1": "aa:bb:cc:00:00:01"}


def test_powershell_single_neighbour_and_failures(windows, monkeypatch):
    one = {"IPAddress": "192.0.2.1", "LinkLayerAddress": "AA-BB-CC-00-00-01"}
    monkeypatch.setattr(arp.subprocess, "check_output", lambda *a, **k: json.dumps(one).encode())
    assert arp.get_powershell_neighbors() == {"192.0.2.1": "aa:bb:cc:00:00:01"}

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("powershell", 10)

    monkeypatch.setattr(arp.subprocess, "check_output", timeout)
    assert arp.get_powershell_neighbors() == {}


def test_powershell_neighbours_only_on_windows(linux):
    assert arp.get_powershell_neighbors() == {}


# --- combining the tables -----------------------------------------------------------------------

async def test_linux_tables_drop_stale_entries_then_add_neighbours(linux, monkeypatch):
    monkeypatch.setattr(arp, "get_local_arp_table", lambda: {"192.0.2.7": "aa:bb:cc:00:00:07", "192.0.2.5": "aa:bb:cc:00:00:05"})
    monkeypatch.setattr(arp, "get_linux_stale_ips", lambda: {"192.0.2.7"})
    monkeypatch.setattr(arp, "get_linux_neighbors", lambda: {"192.0.2.1": "aa:bb:cc:00:00:01"})
    assert await arp._collect_arp_maps() == {"192.0.2.5": "aa:bb:cc:00:00:05", "192.0.2.1": "aa:bb:cc:00:00:01"}


async def test_windows_tables_add_powershell_neighbours(windows, monkeypatch):
    monkeypatch.setattr(arp, "get_local_arp_table", lambda: {"192.0.2.5": "aa:bb:cc:00:00:05"})
    monkeypatch.setattr(arp, "get_powershell_neighbors", lambda: {"192.0.2.1": "aa:bb:cc:00:00:01"})
    assert await arp._collect_arp_maps() == {"192.0.2.5": "aa:bb:cc:00:00:05", "192.0.2.1": "aa:bb:cc:00:00:01"}


# --- active probe -----------------------------------------------------------------------------

@pytest.fixture
def probes(monkeypatch):
    sent = []

    async def probe(ip):
        sent.append(("udp", ip))

    async def ping(ip, timeout):
        sent.append(("ping", ip))
        return False

    async def no_sleep(_):
        return None

    monkeypatch.setattr(arp, "trigger_arp_probe", probe)
    monkeypatch.setattr("app.scanner.utils.ping_host_async", ping)
    monkeypatch.setattr(arp.asyncio, "sleep", no_sleep)
    return sent


async def test_probe_fills_in_macs_found_afterwards(probes, monkeypatch):
    hosts = [{"ip": "192.0.2.5", "mac": "aa:bb:cc:00:00:05"}, {"ip": "192.0.2.9", "mac": None}]
    arp_map = {"192.0.2.5": "aa:bb:cc:00:00:05"}
    monkeypatch.setattr(arp, "get_local_arp_table", lambda: {"192.0.2.9": "aa:bb:cc:00:00:09"})

    await arp._probe_and_retry_missing(hosts, arp_map)

    assert probes == [("udp", "192.0.2.9"), ("ping", "192.0.2.9")]
    assert hosts[1]["mac"] == "aa:bb:cc:00:00:09"
    assert arp_map["192.0.2.9"] == "aa:bb:cc:00:00:09"


async def test_probe_does_nothing_when_every_host_has_a_mac(probes):
    await arp._probe_and_retry_missing([{"ip": "192.0.2.5", "mac": "aa:bb:cc:00:00:05"}], {})
    assert probes == []


async def test_probe_with_an_empty_table_afterwards(probes, monkeypatch):
    hosts = [{"ip": "192.0.2.9", "mac": None}]
    monkeypatch.setattr(arp, "get_local_arp_table", lambda: {})
    await arp._probe_and_retry_missing(hosts, {})
    assert hosts[0]["mac"] is None


async def test_trigger_arp_probe_sends_one_datagram_per_port(monkeypatch):
    sent = []

    class Transport:
        def sendto(self, data, addr):
            sent.append(addr)

        def close(self):
            pass

    class Loop:
        async def create_datagram_endpoint(self, factory, remote_addr):
            if remote_addr[1] == 5355:
                raise OSError("no route")
            return Transport(), None

    monkeypatch.setattr(arp.asyncio, "get_running_loop", lambda: Loop())
    await arp.trigger_arp_probe("192.0.2.9")
    assert sent == [("192.0.2.9", 137), ("192.0.2.9", 5353)]


# --- gateway / proxy-ARP filter -----------------------------------------------------------------

def test_filter_reads_local_subnets_when_none_are_given(monkeypatch):
    monkeypatch.setattr("app.scanner.utils.get_local_subnets", lambda: [SimpleNamespace(subnet="192.0.2.0/24")])
    shared = {"192.0.2.1": "aa:bb:cc:00:00:01", "198.51.100.5": "aa:bb:cc:00:00:01"}
    assert arp._filter_gateway_and_proxy_macs(shared) == {"192.0.2.1": "aa:bb:cc:00:00:01"}


def test_filter_survives_broken_subnet_sources(monkeypatch):
    def broken():
        raise RuntimeError("no interfaces")

    monkeypatch.setattr("app.scanner.utils.get_local_subnets", broken)
    unique = {"192.0.2.1": "aa:bb:cc:00:00:01"}
    assert arp._filter_gateway_and_proxy_macs(unique) == unique
    # A malformed subnet entry is skipped
    assert arp._filter_gateway_and_proxy_macs(unique, ["not-a-cidr", None]) == unique


def test_filter_keeps_a_shared_mac_on_an_unparsable_ip():
    shared = {"not-an-ip": "aa:bb:cc:00:00:01", "also-bad": "aa:bb:cc:00:00:01"}
    assert arp._filter_gateway_and_proxy_macs(shared, []) == shared


def test_filter_strips_a_proxy_arp_mac_across_remote_subnets():
    shared = {"198.51.100.5": "aa:bb:cc:00:00:01", "203.0.113.5": "aa:bb:cc:00:00:01"}
    assert arp._filter_gateway_and_proxy_macs(shared, ["192.0.2.0/24"]) == {}


def test_filter_keeps_a_shared_mac_within_one_remote_subnet():
    # Two IPs of the same /24 on one MAC (e.g. a host with an alias): kept
    shared = {"198.51.100.5": "aa:bb:cc:00:00:01", "198.51.100.6": "aa:bb:cc:00:00:01"}
    assert arp._filter_gateway_and_proxy_macs(shared, ["192.0.2.0/24"]) == shared


# --- resolve_mac_addresses end to end -------------------------------------------------------------

async def test_resolve_strips_gateway_macs_clears_unknown_ones_and_appends_new_hosts(monkeypatch):
    async def tables():
        return {"192.0.2.1": "aa:bb:cc:00:00:01", "198.51.100.5": "aa:bb:cc:00:00:01", "192.0.2.20": "aa:bb:cc:00:00:20"}

    async def no_probe(hosts, arp_map):
        return None

    monkeypatch.setattr(arp, "_collect_arp_maps", tables)
    monkeypatch.setattr(arp, "_probe_and_retry_missing", no_probe)
    monkeypatch.setattr("app.scanner.utils.get_local_subnets", lambda: ["192.0.2.0/24"])
    monkeypatch.setattr(arp, "get_vendor", lambda mac: "Vendor")
    hosts = [{"ip": "198.51.100.5", "mac": "aa:bb:cc:00:00:01"}, {"ip": "192.0.2.30", "mac": "aa:bb:cc:00:00:30"}]

    result = await arp.resolve_mac_addresses(hosts)

    by_ip = {h["ip"]: h for h in result}
    assert by_ip["192.0.2.1"]["mac"] == "aa:bb:cc:00:00:01"  # the gateway keeps its own MAC
    assert by_ip["192.0.2.30"]["mac"] is None  # a MAC no table knows any more is cleared
    assert by_ip["192.0.2.20"] == {"ip": "192.0.2.20", "mac": "aa:bb:cc:00:00:20", "hostname": None, "vendor": "Vendor"}


async def test_resolve_survives_errors(monkeypatch):
    async def broken():
        raise RuntimeError("arp exploded")

    monkeypatch.setattr(arp, "_collect_arp_maps", broken)
    hosts = [{"ip": "192.0.2.5", "mac": None}]
    assert await arp.resolve_mac_addresses(hosts) == hosts
