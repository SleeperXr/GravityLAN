import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from app.scanner.discovery import (
    discover_hosts_simple,
    _parse_nmap_report,
    _build_networks,
    _build_nmap_args,
    _record_found_host,
)


class FakeStream:
    """Minimal stand-in for asyncio.StreamReader backed by a byte string."""

    def __init__(self, data: bytes):
        self._lines = data.splitlines(keepends=True)
        self._idx = 0

    async def readline(self):
        if self._idx >= len(self._lines):
            return b""
        line = self._lines[self._idx]
        self._idx += 1
        return line


class FakeProc:
    """Stand-in for an asyncio subprocess with a pre-fed stdout stream."""

    def __init__(self, stdout_data: bytes, returncode: int = 0, stderr: bytes = b""):
        self.stdout = FakeStream(stdout_data)
        self.stderr = FakeStream(stderr)
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self):
        # Same order as asyncio.subprocess.Process: (stdout, stderr); stdout was streamed already
        return b"", self._stderr

    async def wait(self):
        return self.returncode


@pytest.mark.asyncio
async def test_parse_nmap_report_plain_ip():
    hostname, ip = _parse_nmap_report("Nmap scan report for 192.168.1.10")
    assert hostname is None
    assert ip == "192.168.1.10"


@pytest.mark.asyncio
async def test_parse_nmap_report_with_hostname():
    hostname, ip = _parse_nmap_report("Nmap scan report for sleeper-pc (192.168.100.10)")
    assert hostname == "sleeper-pc"
    assert ip == "192.168.100.10"


@pytest.mark.asyncio
async def test_parse_nmap_report_returns_none_for_unrelated_lines():
    assert _parse_nmap_report("Nmap done: 256 IP addresses (1 host up) scanned") is None
    assert _parse_nmap_report("not a report at all") is None


def test_build_networks_groups_by_24():
    networks = _build_networks(["192.168.1.1", "192.168.1.200", "10.0.0.5"])
    assert networks == {
        "192.168.1.0/24": ["192.168.1.1", "192.168.1.200"],
        "10.0.0.0/24": ["10.0.0.5"],
    }


def test_build_networks_skips_invalid_ips():
    networks = _build_networks(["not-an-ip", "192.168.1.1"])
    assert networks == {"192.168.1.0/24": ["192.168.1.1"]}


def test_build_nmap_args_small_list_scans_ips_directly():
    args = _build_nmap_args("192.168.1.0/24", ["192.168.1.1", "192.168.1.2"], None)
    assert args == ["nmap", "-sn", "192.168.1.1", "192.168.1.2"]


def test_build_nmap_args_large_list_uses_network_with_dns():
    targets = [f"192.168.1.{i}" for i in range(1, 51)]
    args = _build_nmap_args("192.168.1.0/24", targets, "8.8.8.8")
    assert args == ["nmap", "-sn", "--dns-servers", "8.8.8.8", "192.168.1.0/24"]


@pytest.mark.asyncio
async def test_record_found_host_appends_and_notifies():
    discovered = []
    callback = AsyncMock()
    await _record_found_host(discovered, "192.168.1.5", "host-a", callback)
    assert discovered == [{"ip": "192.168.1.5", "mac": None, "hostname": "host-a"}]
    callback.assert_awaited_once_with({"ip": "192.168.1.5", "mac": None, "hostname": "host-a"})


@pytest.mark.asyncio
async def test_record_found_host_dedups_existing_ip():
    discovered = [{"ip": "192.168.1.5", "mac": None, "hostname": "host-a"}]
    callback = AsyncMock()
    await _record_found_host(discovered, "192.168.1.5", "host-b", callback)
    assert len(discovered) == 1
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_discover_hosts_simple_uses_nmap_stream():
    proc = FakeProc(
        b"Nmap scan report for 192.168.1.10\n"
        b"Nmap scan report for sleeper (192.168.1.11)\n",
        returncode=0,
    )
    with (
        patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
        patch("app.scanner.discovery.resolve_mac_addresses", new=AsyncMock()) as resolve_mac,
    ):
        hosts = await discover_hosts_simple(["192.168.1.1"])

    assert {h["ip"] for h in hosts} == {"192.168.1.10", "192.168.1.11"}
    assert hosts[0]["hostname"] is None
    assert hosts[1]["hostname"] == "sleeper"
    resolve_mac.assert_awaited_once()


@pytest.mark.asyncio
async def test_discover_hosts_simple_nonzero_nmap_returncode_still_returns_streamed_hosts():
    proc = FakeProc(b"Nmap scan report for 192.168.1.10\n", returncode=1, stderr=b"timeout")
    with (
        patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
        patch("app.scanner.discovery.resolve_mac_addresses", new=AsyncMock()),
    ):
        hosts = await discover_hosts_simple(["192.168.1.1"])

    assert [h["ip"] for h in hosts] == ["192.168.1.10"]


@pytest.mark.asyncio
async def test_nmap_failure_logs_stderr_not_stdout(caplog):
    proc = FakeProc(b"", returncode=1, stderr=b"dnet: Failed to open device eth0")
    with (
        patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
        patch("app.scanner.discovery._manual_discovery", new=AsyncMock()),
        patch("app.scanner.discovery.resolve_mac_addresses", new=AsyncMock()),
        caplog.at_level("WARNING", logger="app.scanner.discovery"),
    ):
        await discover_hosts_simple(["192.168.1.1"])

    assert "Failed to open device eth0" in caplog.text


@pytest.mark.asyncio
async def test_nmap_scans_each_network_only_with_its_own_ips():
    procs = [FakeProc(b""), FakeProc(b"")]
    create = AsyncMock(side_effect=procs)
    targets = ["192.168.1.10", "10.0.0.5", "192.168.1.11"]
    with (
        patch("asyncio.create_subprocess_exec", new=create),
        patch("app.scanner.discovery._manual_discovery", new=AsyncMock()),
        patch("app.scanner.discovery.resolve_mac_addresses", new=AsyncMock()),
    ):
        await discover_hosts_simple(targets)

    scanned = sorted(call.args[2:] for call in create.call_args_list)
    assert scanned == [("10.0.0.5",), ("192.168.1.10", "192.168.1.11")]


@pytest.mark.asyncio
async def test_discover_hosts_simple_uses_sync_fallback_when_async_unsupported():
    report = "Nmap scan report for 192.168.1.5\n"
    with (
        patch("asyncio.create_subprocess_exec", side_effect=NotImplementedError),
        patch("app.scanner.discovery._run_sync_nmap", return_value=(report, 0)),
        patch("app.scanner.discovery.resolve_mac_addresses", new=AsyncMock()) as resolve_mac,
    ):
        hosts = await discover_hosts_simple(["192.168.1.1"])

    assert [h["ip"] for h in hosts] == ["192.168.1.5"]
    resolve_mac.assert_awaited_once()


@pytest.mark.asyncio
async def test_discover_hosts_simple_falls_back_to_manual_when_nmap_finds_nothing():
    with (
        patch("asyncio.create_subprocess_exec", side_effect=NotImplementedError),
        patch("app.scanner.discovery._run_sync_nmap", return_value=("", 1)),
        patch("app.scanner.discovery.trigger_arp_probe", new=AsyncMock()),
        patch("app.scanner.discovery.ping_host_async", side_effect=lambda ip, t: ip == "192.168.1.7"),
        patch("app.scanner.discovery.check_port_async", new=AsyncMock(return_value=False)),
        patch("app.scanner.discovery.resolve_mac_addresses", new=AsyncMock()) as resolve_mac,
    ):
        hosts = await discover_hosts_simple(["192.168.1.7", "192.168.1.8"])

    assert [h["ip"] for h in hosts] == ["192.168.1.7"]
    resolve_mac.assert_awaited_once()


@pytest.mark.asyncio
async def test_discover_hosts_simple_manual_fallback_uses_tcp_ports_when_ping_fails():
    ping_results = {
        "192.168.1.7": False,
        "192.168.1.8": False,
    }
    port_results = {
        ("192.168.1.8", 445): True,
    }
    with (
        patch("asyncio.create_subprocess_exec", side_effect=NotImplementedError),
        patch("app.scanner.discovery._run_sync_nmap", return_value=("", 1)),
        patch("app.scanner.discovery.trigger_arp_probe", new=AsyncMock()),
        patch("app.scanner.discovery.ping_host_async", side_effect=lambda ip, t: ping_results[ip]),
        patch(
            "app.scanner.discovery.check_port_async",
            side_effect=lambda ip, port, t: port_results.get((ip, port), False),
        ),
        patch("app.scanner.discovery.resolve_mac_addresses", new=AsyncMock()),
    ):
        hosts = await discover_hosts_simple(["192.168.1.7", "192.168.1.8"])

    assert [h["ip"] for h in hosts] == ["192.168.1.8"]


@pytest.mark.asyncio
async def test_discover_hosts_simple_fatal_error_falls_back_to_manual():
    with (
        patch("asyncio.create_subprocess_exec", side_effect=OSError("nmap not installed")),
        patch("app.scanner.discovery.trigger_arp_probe", new=AsyncMock()),
        patch("app.scanner.discovery.ping_host_async", new=AsyncMock(return_value=False)),
        patch("app.scanner.discovery.check_port_async", new=AsyncMock(return_value=False)),
        patch("app.scanner.discovery.resolve_mac_addresses", new=AsyncMock()) as resolve_mac,
    ):
        hosts = await discover_hosts_simple(["192.168.1.1"])

    assert hosts == []
    resolve_mac.assert_awaited_once()


@pytest.mark.asyncio
async def test_discover_hosts_simple_cancel_event_skips_scanning():
    cancel_event = asyncio.Event()
    cancel_event.set()
    with (
        patch("asyncio.create_subprocess_exec", new=AsyncMock()) as create_proc,
        patch("app.scanner.discovery.resolve_mac_addresses", new=AsyncMock()) as resolve_mac,
    ):
        hosts = await discover_hosts_simple(["192.168.1.1"], cancel_event=cancel_event)

    assert hosts == []
    create_proc.assert_not_awaited()
    resolve_mac.assert_awaited_once()


@pytest.mark.asyncio
async def test_discover_hosts_simple_empty_targets_returns_empty():
    with patch("app.scanner.discovery.resolve_mac_addresses", new=AsyncMock()) as resolve_mac:
        hosts = await discover_hosts_simple([])

    assert hosts == []
    resolve_mac.assert_awaited_once()

class HangingProc:
    """nmap that reports one host and then never finishes."""

    def __init__(self):
        self.returncode = None
        self.terminated = False
        self.stdout = self
        self._lines = [b"Nmap scan report for 192.168.1.10\n"]

    async def readline(self):
        if self._lines:
            return self._lines.pop()
        await asyncio.sleep(3600)

    async def communicate(self):
        if self.terminated:
            self.returncode = -15
            return b"", b""
        await asyncio.sleep(3600)

    def terminate(self):
        self.terminated = True

    def kill(self):
        pass

    async def wait(self):
        if self.terminated:
            self.returncode = -15
        return self.returncode


@pytest.mark.asyncio
async def test_a_hanging_nmap_is_stopped_after_the_timeout_and_keeps_its_hosts():
    from app.scanner import discovery

    proc = HangingProc()
    discovered = []
    with (
        patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
        patch.object(discovery, "NMAP_DISCOVERY_TIMEOUT", 0.05),
    ):
        await discovery._scan_network_once("192.168.1.0/24", ["192.168.1.1"], None, discovered, None)

    assert proc.terminated and proc.returncode == -15
    assert [h["ip"] for h in discovered] == ["192.168.1.10"]


@pytest.mark.asyncio
async def test_cancelling_stops_a_running_nmap_at_once():
    from app.scanner import discovery

    proc = HangingProc()
    cancel = asyncio.Event()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
        task = asyncio.create_task(
            discovery._scan_network_once("192.168.1.0/24", ["192.168.1.1"], None, [], None, cancel)
        )
        await asyncio.sleep(0.01)
        cancel.set()
        await asyncio.wait_for(task, timeout=1.0)

    assert proc.terminated


def test_the_sync_fallback_stops_nmap_at_the_timeout():
    """Without async subprocesses (some Windows loops) a hanging nmap is bounded as well."""
    import sys
    import time
    from app.scanner import discovery

    started = time.monotonic()
    stdout, returncode = discovery._run_sync_nmap([sys.executable, "-c", "print('x', flush=True); import time; time.sleep(30)"], timeout=0.3)
    assert time.monotonic() - started < 10
    assert returncode != 0
    assert "x" in stdout


def test_the_sync_fallback_stops_nmap_when_the_scan_is_cancelled():
    import sys
    import threading
    import time
    from app.scanner import discovery

    cancel = asyncio.Event()
    threading.Timer(0.2, cancel.set).start()
    started = time.monotonic()
    _, returncode = discovery._run_sync_nmap([sys.executable, "-c", "import time; time.sleep(30)"], timeout=60, cancel_event=cancel)
    assert time.monotonic() - started < 10
    assert returncode != 0


def test_the_sync_fallback_returns_a_finished_scan_unchanged():
    import sys
    from app.scanner import discovery

    stdout, returncode = discovery._run_sync_nmap([sys.executable, "-c", "print('Nmap scan report for 192.168.1.10')"], timeout=30)
    assert returncode == 0 and "192.168.1.10" in stdout
