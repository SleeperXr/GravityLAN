"""The network probes and helpers of app/scanner/utils.py, run for real (elsewhere they are always mocked):
time zones, default groups, the PowerShell and socket subnet fallbacks, TCP checks, ping parsing and TLS expiry."""

import asyncio
import datetime as dt
import json
import socket
import ssl
import subprocess
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.scanner.utils as utils
from app.models.device import DeviceGroup
from app.schemas.scan import SubnetInfo


# --- small helpers --------------------------------------------------------------------------------

def test_ensure_utc():
    naive = dt.datetime(2026, 11, 8, 12, 0)
    assert utils.ensure_utc(naive).tzinfo is dt.UTC
    aware = dt.datetime(2026, 11, 8, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))
    assert utils.ensure_utc(aware) is aware
    assert utils.ensure_utc(None) is None


def test_auto_scan_subnets_leave_out_virtual_ones(monkeypatch):
    found = [
        SubnetInfo(interface_name="eth0", ip_address="192.0.2.5", subnet="192.0.2.0/24", netmask="255.255.255.0", is_virtual=False),
        SubnetInfo(interface_name="docker0", ip_address="172.17.0.1", subnet="172.17.0.0/16", netmask="255.255.0.0", is_virtual=True),
    ]
    monkeypatch.setattr(utils, "get_local_subnets", lambda: found)
    assert utils.get_auto_scan_subnets() == ["192.0.2.0/24"]


@pytest.mark.asyncio
async def test_default_groups_are_created_once(db):
    db.add(DeviceGroup(name="Server", icon="server", sort_order=1, is_default=True))
    await db.commit()

    first = await utils.ensure_default_groups(db)
    assert set(first) == {g["name"] for g in utils.DEFAULT_GROUPS}
    again = await utils.ensure_default_groups(db, commit=False)
    assert again == first
    names = (await db.execute(select(DeviceGroup.name))).scalars().all()
    assert sorted(names) == sorted(first)


# --- subnet fallbacks -----------------------------------------------------------------------------

def test_powershell_subnets(monkeypatch):
    out = json.dumps([
        {"InterfaceAlias": "Ethernet", "IPAddress": "192.0.2.10", "PrefixLength": 24},
        {"InterfaceAlias": "vEthernet (WSL)", "IPAddress": "198.51.100.1", "PrefixLength": 20},
        {"InterfaceAlias": "Loopback", "IPAddress": "127.0.0.1", "PrefixLength": 8},
        {"InterfaceAlias": "No prefix", "IPAddress": "203.0.113.9", "PrefixLength": None},
    ]).encode("cp850")
    monkeypatch.setattr(utils.subprocess, "check_output", lambda *a, **k: out)
    subnets: list = []
    utils._collect_powershell_subnets(subnets, set())
    assert [(s.subnet, s.is_virtual) for s in subnets] == [("192.0.2.0/24", False), ("198.51.96.0/20", True)]


def test_powershell_single_adapter_and_failure(monkeypatch):
    # One adapter comes back as an object, not a list
    one = json.dumps({"InterfaceAlias": "Ethernet", "IPAddress": "192.0.2.10", "PrefixLength": 16}).encode()
    monkeypatch.setattr(utils.subprocess, "check_output", lambda *a, **k: one)
    subnets: list = []
    utils._collect_powershell_subnets(subnets, set())
    assert [s.subnet for s in subnets] == ["192.0.0.0/16"]

    def fail(*_a, **_k):
        raise subprocess.TimeoutExpired("powershell", 10)

    monkeypatch.setattr(utils.subprocess, "check_output", fail)
    subnets = []
    utils._collect_powershell_subnets(subnets, set())
    assert subnets == []


def test_socket_subnets(monkeypatch):
    monkeypatch.setattr(utils.socket, "gethostname", lambda: "host")
    monkeypatch.setattr(utils.socket, "gethostbyname_ex", lambda _h: ("host", [], ["127.0.1.1", "192.0.2.7"]))
    subnets: list = []
    utils._collect_socket_subnets(subnets, set())
    assert [(s.interface_name, s.subnet) for s in subnets] == [("default", "192.0.2.0/24")]

    def unresolvable(_h):
        raise socket.gaierror("no name")

    monkeypatch.setattr(utils.socket, "gethostbyname_ex", unresolvable)
    subnets = []
    utils._collect_socket_subnets(subnets, set())
    assert subnets == []


def test_local_subnets_fall_through_to_the_socket_stage(monkeypatch):
    monkeypatch.setattr(utils, "_collect_psutil_subnets", lambda s, seen: None)
    monkeypatch.setattr(utils, "_collect_netifaces_subnets", lambda s, seen: None)
    monkeypatch.setattr(utils, "_collect_powershell_subnets", lambda s, seen: None)
    monkeypatch.setattr(utils, "_collect_socket_subnets", lambda s, seen: utils._add_subnet(s, seen, "default", "192.0.2.7", "255.255.255.0"))
    assert [s.subnet for s in utils.get_local_subnets()] == ["192.0.2.0/24"]


# --- TCP --------------------------------------------------------------------------------------------

@pytest.fixture
async def open_port():
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    yield port
    server.close()
    await server.wait_closed()


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_check_port_async(open_port):
    assert await utils.check_port_async("127.0.0.1", open_port) is True
    assert await utils.check_port_async("127.0.0.1", _closed_port()) is False


@pytest.mark.asyncio
async def test_tcp_latency(open_port):
    rtt = await utils.measure_tcp_latency_ms("127.0.0.1", open_port)
    assert isinstance(rtt, float) and rtt >= 0
    assert await utils.measure_tcp_latency_ms("127.0.0.1", _closed_port()) is None


# --- ping -------------------------------------------------------------------------------------------

def _ping_result(monkeypatch, returncode=0, stdout=""):
    seen = {}

    def run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(utils.subprocess, "run", run)
    return seen


@pytest.mark.asyncio
async def test_ping_needs_a_ttl_reply(monkeypatch):
    seen = _ping_result(monkeypatch, 0, "Reply from 192.0.2.1: bytes=32 time=3ms TTL=64")
    assert await utils.ping_host_async("192.0.2.1") is True
    assert seen["command"][0] == "ping" and seen["command"][-1] == "192.0.2.1"
    # Windows answers 0 for "Destination host unreachable" too
    _ping_result(monkeypatch, 0, "Reply from 192.0.2.254: Destination host unreachable.")
    assert await utils.ping_host_async("192.0.2.1") is False
    _ping_result(monkeypatch, 1, "")
    assert await utils.ping_host_async("192.0.2.1") is False


@pytest.mark.asyncio
async def test_ping_survives_a_broken_ping(monkeypatch):
    def broken(*_a, **_k):
        raise FileNotFoundError("ping")

    monkeypatch.setattr(utils.subprocess, "run", broken)
    assert await utils.ping_host_async("192.0.2.1") is False
    assert await utils.measure_ping_latency_ms("192.0.2.1") is None


@pytest.mark.parametrize(
    "stdout, expected",
    [
        ("64 bytes from 192.0.2.1: icmp_seq=1 ttl=64 time=1.234 ms", 1.23),
        ("Antwort von 192.0.2.1: Bytes=32 Zeit=4ms TTL=64", 4.0),
        ("Reply from 192.0.2.1: bytes=32 time<1ms TTL=128", 0.5),
    ],
)
@pytest.mark.asyncio
async def test_ping_latency_reads_the_reported_time(monkeypatch, stdout, expected):
    _ping_result(monkeypatch, 0, stdout)
    assert await utils.measure_ping_latency_ms("192.0.2.1") == expected


@pytest.mark.asyncio
async def test_ping_latency_without_a_time_falls_back_or_gives_none(monkeypatch):
    # TTL but no readable time: the measured wall time
    _ping_result(monkeypatch, 0, "Reply from 192.0.2.1 TTL=64")
    assert isinstance(await utils.measure_ping_latency_ms("192.0.2.1"), float)
    _ping_result(monkeypatch, 0, "Destination host unreachable.")
    assert await utils.measure_ping_latency_ms("192.0.2.1") is None
    _ping_result(monkeypatch, 1, None)
    assert await utils.measure_ping_latency_ms("192.0.2.1") is None


# --- TLS --------------------------------------------------------------------------------------------

@pytest.fixture
def tls_port(tmp_path):
    """A local TLS server with a self-signed certificate that runs out in 30 days."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nas.lan")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=30, hours=12))
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_file, key_file)
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    stop = threading.Event()

    def serve():
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            try:
                with ctx.wrap_socket(conn, server_side=True):
                    pass
            except (ssl.SSLError, OSError):
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield port
    stop.set()
    thread.join(2)
    listener.close()


@pytest.mark.asyncio
async def test_ssl_expiry_days_of_a_self_signed_cert(tls_port):
    assert await utils.check_ssl_expiry_days("127.0.0.1", tls_port, hostname="nas.lan") == 30
    # An IP as host name sends no SNI and still reads the certificate
    assert await utils.check_ssl_expiry_days("127.0.0.1", tls_port, hostname="127.0.0.1") == 30


@pytest.mark.asyncio
async def test_ssl_expiry_without_tls_is_none():
    assert await utils.check_ssl_expiry_days("127.0.0.1", _closed_port(), timeout=0.5) is None
