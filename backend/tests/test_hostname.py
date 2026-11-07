"""Tests for hostname resolution helpers (app/scanner/hostname.py)."""

import sys

import pytest

import app.scanner.hostname as hostname


# --- is_ip_like -------------------------------------------------------------

def test_is_ip_like_empty_is_true():
    assert hostname.is_ip_like(None) is True
    assert hostname.is_ip_like("") is True


def test_is_ip_like_ip_and_placeholders():
    assert hostname.is_ip_like("192.168.1.1") is True
    assert hostname.is_ip_like("unbekannt") is True
    assert hostname.is_ip_like("unknown") is True


def test_is_ip_like_real_hostname():
    assert hostname.is_ip_like("my-router") is False
    assert hostname.is_ip_like("printer.local") is False


# --- mask_ip ----------------------------------------------------------------

def test_mask_ip_masks_host_part():
    assert hostname.mask_ip("192.168.1.42") == "192.168.x.x"


def test_mask_ip_handles_malformed():
    assert hostname.mask_ip(None) == ""
    assert hostname.mask_ip("abc") == "x.x.x.x"


# --- _parse_ping_hostname ---------------------------------------------------

def test_parse_ping_hostname_extracts():
    out = (
        "Windows IP Configuration\n\n"
        "Pinging my-router [192.168.1.1] with 32 bytes of data:\n"
        "Reply from 192.168.1.1: bytes=32 time<1ms TTL=64\n"
    )
    assert hostname._parse_ping_hostname(out, "192.168.1.1") == "my-router"


def test_parse_ping_hostname_ignores_own_ip():
    assert hostname._parse_ping_hostname("Pinging 192.168.1.1 [192.168.1.1]", "192.168.1.1") is None


def test_parse_ping_hostname_no_match():
    assert hostname._parse_ping_hostname("no useful output", "10.0.0.1") is None


# --- _try_dig / _resolve_linux_shell ----------------------------------------

class _FakeRun:
    """subprocess.run double that records each command and returns the given stdout."""

    def __init__(self, stdout=""):
        self.calls = []
        self.stdout = stdout

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        return type("Result", (), {"returncode": 0, "stdout": self.stdout})()


def test_try_dig_asks_configured_dns_server(monkeypatch):
    run = _FakeRun("nas.lan.\n")
    monkeypatch.setattr(hostname.subprocess, "run", run)

    assert hostname._try_dig("192.168.1.50", dns_server="192.168.1.2") == "nas.lan"
    assert run.calls == [["dig", "@192.168.1.2", "+short", "-x", "192.168.1.50"]]


def test_try_dig_without_dns_server_uses_system_resolver(monkeypatch):
    run = _FakeRun("")
    monkeypatch.setattr(hostname.subprocess, "run", run)

    assert hostname._try_dig("192.168.1.50") is None
    assert run.calls == [["dig", "+short", "-x", "192.168.1.50"]]


def test_linux_shell_fallback_no_longer_spawns_nmap(monkeypatch):
    """A host without a DNS name used to cost an extra 'nmap -sn' (up to 3 s) per IP."""
    run = _FakeRun("")
    monkeypatch.setattr(hostname.subprocess, "run", run)

    assert hostname._resolve_linux_shell("192.168.1.50", dns_server="192.168.1.2") is None
    assert [cmd[0] for cmd in run.calls] == ["avahi-resolve", "dig"]
    assert "@192.168.1.2" in run.calls[1]


# --- _resolve_shell ---------------------------------------------------------

def test_resolve_shell_linux_delegates(monkeypatch):
    monkeypatch.setattr(hostname.sys, "platform", "linux")
    seen = []
    monkeypatch.setattr(hostname, "_resolve_linux_shell", lambda ip, dns_server=None: seen.append(dns_server) or "linux-name")
    assert hostname._resolve_shell("192.168.1.1", dns_server="192.168.1.2") == "linux-name"
    assert seen == ["192.168.1.2"]


def test_resolve_shell_win32_delegates(monkeypatch):
    monkeypatch.setattr(hostname.sys, "platform", "win32")
    monkeypatch.setattr(hostname, "_resolve_ping_win32", lambda ip: "win-name")
    assert hostname._resolve_shell("192.168.1.1") == "win-name"


# --- cache: found names for an hour, misses only until the next quick scan ---

import pytest
from datetime import datetime, timedelta, timezone


@pytest.fixture
def fresh_lookup(monkeypatch):
    """Every real lookup answers 'fresh-name' and is counted; the cache starts empty."""
    calls = []
    monkeypatch.setattr(hostname, "_dns_cache", {})
    monkeypatch.setattr(hostname, "_resolve_win32", lambda ip: calls.append(ip) or "fresh-name")
    return calls


def _cached(name, seconds_ago):
    return (name, datetime.now(timezone.utc) - timedelta(seconds=seconds_ago))


@pytest.mark.asyncio
async def test_a_miss_is_retried_after_the_negative_ttl(fresh_lookup):
    hostname._dns_cache["10.0.0.5"] = _cached(None, hostname.DNS_NEGATIVE_CACHE_TTL + 5)
    assert await hostname.resolve_hostname("10.0.0.5") == "fresh-name"
    assert fresh_lookup == ["10.0.0.5"]


@pytest.mark.asyncio
async def test_a_recent_miss_and_a_found_name_come_from_the_cache(fresh_lookup):
    hostname._dns_cache["10.0.0.5"] = _cached(None, 60)
    hostname._dns_cache["10.0.0.6"] = _cached("nas.local", 30 * 60)
    assert await hostname.resolve_hostname("10.0.0.5") is None
    assert await hostname.resolve_hostname("10.0.0.6") == "nas.local"
    assert fresh_lookup == []


@pytest.mark.asyncio
async def test_use_cache_false_always_looks_again(fresh_lookup):
    hostname._dns_cache["10.0.0.5"] = _cached(None, 10)
    assert await hostname.resolve_hostname("10.0.0.5", use_cache=False) == "fresh-name"
    assert fresh_lookup == ["10.0.0.5"]


# --- the lookup chain: Win32 API, direct DNS, OS resolver, shell tools --------

from types import SimpleNamespace


class _FakeResolver:
    """dns.resolver.Resolver double: answers ``answer`` or raises it."""

    answer: object = None
    instances: list = []

    def __init__(self):
        self.nameservers = ["system"]
        _FakeResolver.instances.append(self)

    def resolve(self, _name, _rdtype):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def chain(monkeypatch):
    """No Win32 API, a fake DNS resolver; OS resolver and shell tools set per test."""
    import dns.resolver

    _FakeResolver.answer, _FakeResolver.instances = None, []
    monkeypatch.setattr(hostname, "_dns_cache", {})
    monkeypatch.setattr(hostname, "_resolve_win32", lambda ip: None)
    monkeypatch.setattr(hostname, "HAS_DNS_PYTHON", True)
    monkeypatch.setattr(dns.resolver, "Resolver", _FakeResolver)
    monkeypatch.setattr(hostname, "socket", SimpleNamespace(getnameinfo=lambda addr, flags: (addr[0], "0")))
    monkeypatch.setattr(hostname, "_resolve_shell", lambda ip, dns_server=None: None)
    return monkeypatch


@pytest.mark.asyncio
async def test_direct_dns_asks_the_configured_server(chain):
    _FakeResolver.answer = ["nas.lan."]

    assert await hostname.resolve_hostname("192.0.2.5", dns_server="192.0.2.53") == "nas.lan"
    assert _FakeResolver.instances[0].nameservers == ["192.0.2.53"]


@pytest.mark.asyncio
async def test_os_resolver_when_dns_fails(chain):
    _FakeResolver.answer = OSError("no answer")
    chain.setattr(hostname, "socket", SimpleNamespace(getnameinfo=lambda addr, flags: ("pc.lan", "0")))

    assert await hostname.resolve_hostname("192.0.2.5") == "pc.lan"


@pytest.mark.asyncio
async def test_shell_tools_when_the_os_only_echoes_the_ip(chain):
    chain.setattr(hostname, "_resolve_shell", lambda ip, dns_server=None: "tv.local")

    assert await hostname.resolve_hostname("192.0.2.5") == "tv.local"


@pytest.mark.asyncio
async def test_no_name_anywhere_is_remembered_as_a_miss(chain):
    chain.setattr(hostname, "socket", SimpleNamespace(getnameinfo=lambda addr, flags: (_ for _ in ()).throw(OSError())))

    assert await hostname.resolve_hostname("192.0.2.5") is None
    assert hostname._dns_cache["192.0.2.5"][0] is None


@pytest.mark.asyncio
async def test_without_dnspython_the_os_resolver_answers(chain):
    chain.setattr(hostname, "HAS_DNS_PYTHON", False)
    chain.setattr(hostname, "socket", SimpleNamespace(getnameinfo=lambda addr, flags: ("pc.lan", "0")))

    assert await hostname.resolve_hostname("192.0.2.5") == "pc.lan"
    assert _FakeResolver.instances == []


@pytest.mark.asyncio
async def test_a_slow_lookup_times_out_as_a_miss(chain):
    import time

    chain.setattr(hostname, "_resolve_win32", lambda ip: time.sleep(1.3) or "too-late")

    assert await hostname.resolve_hostname("192.0.2.5", timeout=0.0) is None
    assert hostname._dns_cache["192.0.2.5"][0] is None


@pytest.mark.asyncio
async def test_resolve_hostnames_fills_in_what_it_finds(monkeypatch):
    names = {"192.0.2.5": "nas.lan"}

    async def fake_resolve(ip, timeout, dns_server):
        return names.get(ip)

    monkeypatch.setattr(hostname, "resolve_hostname", fake_resolve)
    hosts = [{"ip": "192.0.2.5"}, {"ip": "192.0.2.6", "hostname": "kept"}]

    assert await hostname.resolve_hostnames(hosts) == [{"ip": "192.0.2.5", "hostname": "nas.lan"}, {"ip": "192.0.2.6", "hostname": "kept"}]


@pytest.mark.asyncio
async def test_resolve_hostnames_stops_when_cancelled(monkeypatch):
    import asyncio

    async def must_not_run(*_args):
        raise AssertionError("looked up despite cancellation")

    monkeypatch.setattr(hostname, "resolve_hostname", must_not_run)
    cancel = asyncio.Event()
    cancel.set()

    assert await hostname.resolve_hostnames([{"ip": "192.0.2.5"}], cancel_event=cancel) == [{"ip": "192.0.2.5"}]


def _run_result(returncode=0, stdout=""):
    return lambda cmd, **kwargs: SimpleNamespace(returncode=returncode, stdout=stdout)


def test_try_avahi_reads_the_name(monkeypatch):
    monkeypatch.setattr(hostname.subprocess, "run", _run_result(stdout="192.0.2.5\tnas.local\n"))
    assert hostname._try_avahi("192.0.2.5") == "nas.local"


@pytest.mark.parametrize("run", [_run_result(returncode=1, stdout="Failed"), _run_result(stdout="192.0.2.5"), lambda cmd, **kw: (_ for _ in ()).throw(OSError())])
def test_try_avahi_without_an_answer(monkeypatch, run):
    monkeypatch.setattr(hostname.subprocess, "run", run)
    assert hostname._try_avahi("192.0.2.5") is None


def test_try_dig_without_dig_installed(monkeypatch):
    monkeypatch.setattr(hostname.subprocess, "run", lambda cmd, **kw: (_ for _ in ()).throw(FileNotFoundError()))
    assert hostname._try_dig("192.0.2.5") is None


def test_win32_api_is_only_used_on_windows(monkeypatch):
    monkeypatch.setattr(hostname.sys, "platform", "linux")
    assert hostname._resolve_win32("192.0.2.5") is None
