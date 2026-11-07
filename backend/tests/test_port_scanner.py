"""TCP port scan and the nmap -Pn scan: open ports, fallbacks, cancellation and nmap output."""

import asyncio
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.scanner import port_scanner as ps

IP = "192.0.2.10"


class FakeSocket:
    """socket.socket stand-in: ports in ``open`` connect, others refuse, ``errors`` raise."""

    open: set[int] = set()
    errors: dict[int, type[Exception]] = {}

    def __init__(self, *_args):
        pass

    def settimeout(self, _timeout):
        pass

    def connect_ex(self, address):
        port = address[1]
        if port in self.errors:
            raise self.errors[port]()
        return 0 if port in self.open else 111

    def close(self):
        pass


@pytest.fixture
def sockets(monkeypatch):
    FakeSocket.open, FakeSocket.errors = set(), {}
    # Only the scanner's view of the module: the event loop needs the real sockets
    monkeypatch.setattr(ps, "socket", SimpleNamespace(socket=FakeSocket, AF_INET=2, SOCK_STREAM=1))
    return FakeSocket


@pytest.mark.asyncio
async def test_scan_ports_returns_the_open_ones(sockets):
    sockets.open = {22, 443}

    assert sorted(await ps.scan_ports(IP, ports=[22, 80, 443], gentle=False)) == [22, 443]


@pytest.mark.asyncio
async def test_gentle_scan_finds_the_same_ports(sockets):
    sockets.open = {22, 443}

    assert sorted(await ps.scan_ports(IP, ports=[22, 80, 443], gentle=True)) == [22, 443]


@pytest.mark.asyncio
async def test_scan_ports_uses_the_default_list(sockets):
    sockets.open = {8006}

    assert await ps.scan_ports(IP, gentle=False) == [8006]


@pytest.mark.asyncio
async def test_cancelled_scan_reports_nothing(sockets):
    sockets.open = {22}
    cancel = asyncio.Event()
    cancel.set()

    assert await ps.scan_ports(IP, ports=[22], gentle=False, cancel_event=cancel) == []


@pytest.mark.asyncio
async def test_socket_errors_count_as_closed(sockets):
    sockets.errors = {22: OSError, 80: PermissionError}

    assert await ps.scan_ports(IP, ports=[22, 80], gentle=False) == []


@pytest.mark.asyncio
async def test_smb_falls_back_to_nmap_when_sockets_are_not_allowed(sockets, monkeypatch):
    sockets.errors = {445: PermissionError}
    run = MagicMock(return_value=SimpleNamespace(stdout="445/tcp open  microsoft-ds"))
    monkeypatch.setattr(ps.subprocess, "run", run)

    assert await ps.scan_ports(IP, ports=[445], gentle=False) == [445]
    assert run.call_args.args[0][-1] == IP


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [SimpleNamespace(stdout="445/tcp filtered"), OSError(), subprocess.TimeoutExpired("nmap", 1.5)])
async def test_smb_fallback_closed_or_failing(sockets, monkeypatch, outcome):
    sockets.errors = {445: PermissionError}
    run = MagicMock(side_effect=outcome) if isinstance(outcome, Exception) else MagicMock(return_value=outcome)
    monkeypatch.setattr(ps.subprocess, "run", run)

    assert await ps.scan_ports(IP, ports=[445], gentle=False) == []


def test_parse_nmap_greppable():
    output = (
        "# Nmap 7.94 scan initiated\n"
        "Host: 192.0.2.10 ()\tStatus: Up\n"
        "Host: 192.0.2.10 ()\tPorts: 22/open/tcp//ssh///, 80/closed/tcp//http///, 443/open/tcp//https///\n"
    )

    assert ps._parse_nmap_greppable(output) == [22, 443]


@pytest.mark.parametrize("output", ["", "Host: 192.0.2.10 ()\tStatus: Down\n", "Ports: x/open/tcp//odd///"])
def test_parse_nmap_greppable_without_open_ports(output):
    assert ps._parse_nmap_greppable(output) == []


def test_nmap_command_is_an_argument_list():
    assert ps._build_nmap_command(IP, None) == ["nmap", "-Pn", "--top-ports", "1000", "-oG", "-", IP]
    assert ps._build_nmap_command(IP, "192.0.2.53")[-3:] == ["--dns-servers", "192.0.2.53", IP]


@pytest.mark.asyncio
async def test_nmap_scan_parses_the_output(monkeypatch):
    run = AsyncMock(return_value=(b"Ports: 22/open/tcp//ssh///", b"", 0))
    monkeypatch.setattr(ps, "_run_nmap_async", run)

    assert await ps.nmap_scan(IP, dns_server="192.0.2.53") == [22]
    assert "--dns-servers" in run.await_args.args[0]


@pytest.mark.asyncio
async def test_nmap_scan_keeps_partial_output_of_a_failed_run(monkeypatch):
    monkeypatch.setattr(ps, "_run_nmap_async", AsyncMock(return_value=(b"Ports: 80/open/tcp//http///", b"terminated", 1)))

    assert await ps.nmap_scan(IP) == [80]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [asyncio.TimeoutError(), RuntimeError("boom")])
async def test_nmap_scan_errors_give_no_ports(monkeypatch, error):
    monkeypatch.setattr(ps, "_run_nmap_async", AsyncMock(side_effect=error))

    assert await ps.nmap_scan(IP) == []


class FakeProc:
    def __init__(self, stdout=b"out", stderr=b"", returncode=0, communicate=None):
        self.returncode = None
        self._result = (stdout, stderr)
        self._final = returncode
        self._communicate = communicate
        self.terminated = self.killed = False

    async def communicate(self):
        if self._communicate:
            return await self._communicate()
        self.returncode = self._final
        return self._result

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


@pytest.mark.asyncio
async def test_run_nmap_async_returns_the_process_output(monkeypatch):
    proc = FakeProc(stdout=b"Ports: 22/open/tcp//ssh///", returncode=0)
    monkeypatch.setattr(ps.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))

    assert await ps._run_nmap_async(["nmap", IP], None, IP) == (b"Ports: 22/open/tcp//ssh///", b"", 0)


@pytest.mark.asyncio
async def test_run_nmap_async_survives_a_communication_error(monkeypatch):
    async def broken():
        raise OSError("pipe closed")

    proc = FakeProc(communicate=broken)
    monkeypatch.setattr(ps.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))

    assert await ps._run_nmap_async(["nmap", IP], None, IP) == (b"", b"", None)


@pytest.mark.asyncio
async def test_run_nmap_async_falls_back_without_async_subprocesses(monkeypatch):
    monkeypatch.setattr(ps.asyncio, "create_subprocess_exec", AsyncMock(side_effect=NotImplementedError()))
    fallback = AsyncMock(return_value=(b"x", b"", 0))
    monkeypatch.setattr(ps, "_run_nmap_fallback", fallback)

    assert await ps._run_nmap_async(["nmap", IP], None, IP) == (b"x", b"", 0)
    fallback.assert_awaited_once_with(["nmap", IP])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (SimpleNamespace(stdout=b"out", stderr=b"", returncode=0), (b"out", b"", 0)),
        (subprocess.TimeoutExpired("nmap", 45), (b"", b"Timeout", 1)),
        (OSError("nmap not found"), (b"", b"nmap not found", 1)),
    ],
)
async def test_run_nmap_fallback(monkeypatch, outcome, expected):
    run = MagicMock(side_effect=outcome) if isinstance(outcome, Exception) else MagicMock(return_value=outcome)
    monkeypatch.setattr(subprocess, "run", run)

    assert await ps._run_nmap_fallback(["nmap", IP]) == expected


@pytest.mark.asyncio
async def test_cancellation_terminates_then_kills_nmap():
    cancel = asyncio.Event()
    cancel.set()
    proc = FakeProc()

    await ps._wait_for_cancel(cancel, proc)

    assert proc.terminated and proc.killed


@pytest.mark.asyncio
async def test_cancellation_leaves_a_finished_nmap_alone():
    cancel = asyncio.Event()
    cancel.set()
    proc = FakeProc()
    proc.returncode = 0

    await ps._wait_for_cancel(cancel, proc)

    assert not proc.terminated


@pytest.mark.asyncio
async def test_no_cancel_event_returns_at_once():
    await asyncio.wait_for(ps._wait_for_cancel(None, FakeProc()), timeout=1)
