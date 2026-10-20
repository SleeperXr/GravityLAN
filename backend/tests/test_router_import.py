"""Importing subnets/VLANs from a router: SNMP and UniFi providers, preview, apply, credentials.

Router answers are mocked: SNMP through a fake table walker, UniFi through an
httpx MockTransport (plus one real local TLS server for the certificate pin).
"""

import asyncio
import datetime
import ipaddress
import json
import ssl

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app.models.network import Subnet
from app.models.router_import import RouterImportSource
from app.services import secret_vault
from app.services.router_import import base, snmp
from app.services.router_import.base import RouterConnection, RouterImportError, resolve_lan_target
from app.services.router_import.snmp import SnmpProvider, parse_vlan_id
from app.services.router_import.unifi import (
    API_PREFIX,
    CertificatePin,
    UnifiProvider,
    certificate_fingerprint,
    normalize_fingerprint,
    pick_site,
)
from app.services.secret_vault import SecretVault

PREVIEW = "/api/network/router-import/preview"
APPLY = "/api/network/router-import/apply"
SOURCES = "/api/network/router-import/sources"


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_vault(tmp_path, monkeypatch):
    vault = SecretVault(key_file=tmp_path / "ssh_vault.key", env_key="")
    monkeypatch.setattr(secret_vault, "vault", vault)
    return vault


# --- SNMP fixtures -----------------------------------------------------------

def _ip_addr_rows(entries):
    """ipAddrTable rows for (address, ifIndex, netmask) entries."""
    rows = []
    for addr, if_index, mask in entries:
        index = tuple(int(p) for p in addr.split("."))
        rows.append((snmp.OID_IP_ADDR_ENTRY + (1,) + index, addr))
        rows.append((snmp.OID_IP_ADDR_ENTRY + (2,) + index, if_index))
        rows.append((snmp.OID_IP_ADDR_ENTRY + (3,) + index, mask))
    return rows


def _column(base_oid, values):
    return [(base_oid + (index,), value) for index, value in values.items()]


# A UniFi-like gateway: br0 = default LAN, br10/br20 = VLAN bridges, eth4 = WAN
UNIFI_LIKE_TABLES = {
    snmp.OID_IP_ADDR_ENTRY: _ip_addr_rows([
        ("192.168.1.1", 5, "255.255.255.0"),
        ("192.168.10.1", 6, "255.255.255.0"),
        ("192.168.20.1", 7, "255.255.254.0"),
        ("84.12.34.56", 4, "255.255.255.0"),   # public WAN address: skipped
        ("127.0.0.1", 1, "255.0.0.0"),          # loopback: skipped
        ("10.255.0.1", 8, "255.255.255.255"),   # /32: skipped
    ]),
    snmp.OID_IF_NAME: _column(snmp.OID_IF_NAME, {1: "lo", 4: "eth4", 5: "br0", 6: "br10", 7: "br20", 8: "wg0"}),
    snmp.OID_IF_ALIAS: _column(snmp.OID_IF_ALIAS, {6: "Kameras", 7: ""}),
    snmp.OID_VLAN_STATIC_NAME: _column(snmp.OID_VLAN_STATIC_NAME, {20: "IoT"}),
}


class FakeWalker:
    def __init__(self, tables=None, error=None):
        self.tables = tables or {}
        self.error = error
        self.walked = []
        self.closed = False

    async def walk(self, oid):
        self.walked.append(oid)
        if self.error:
            raise RouterImportError(self.error, 502)
        return list(self.tables.get(oid, []))

    def close(self):
        self.closed = True


@pytest.fixture
def snmp_router(monkeypatch):
    """Answer SNMP with the given tables; returns a setter and the walkers created."""
    state = {"tables": UNIFI_LIKE_TABLES, "error": None, "walkers": []}

    def open_walker(self, conn):
        walker = FakeWalker(state["tables"], state["error"])
        walker.conn = conn
        state["walkers"].append(walker)
        return walker

    monkeypatch.setattr(SnmpProvider, "open_walker", open_walker)
    return state


# --- SNMP --------------------------------------------------------------------

@pytest.mark.parametrize("name, vlan", [
    ("br10", 10), ("br0", None), ("eth0.20", 20), ("switch0.30", 30), ("vlan40", 40),
    ("Vlan50", 50), ("igb1_vlan60", 60), ("vlan0.70", 70), ("br-lan", None), ("eth0", None),
    ("br5000", None), ("irb.80", 80), (None, None),
])
def test_parse_vlan_id(name, vlan):
    assert parse_vlan_id(name) == vlan


@pytest.mark.asyncio
async def test_snmp_reads_lan_networks_with_names_and_vlans():
    walker = FakeWalker(UNIFI_LIKE_TABLES)
    networks = await snmp.read_networks(walker.walk)
    assert [(n.cidr, n.gateway_ip, n.vlan_id, n.name, n.interface) for n in networks] == [
        ("192.168.1.0/24", "192.168.1.1", None, "br0", "br0"),
        ("192.168.10.0/24", "192.168.10.1", 10, "Kameras", "br10"),   # ifAlias wins
        ("192.168.20.0/23", "192.168.20.1", 20, "IoT", "br20"),       # Q-BRIDGE VLAN name
    ]


@pytest.mark.asyncio
async def test_snmp_falls_back_to_ip_address_table():
    prefix_pointer = (1, 3, 6, 1, 2, 1, 4, 32, 1, 5, 7, 1, 4, 192, 168, 30, 0, 24)
    entry = snmp.OID_IP_ADDRESS_ENTRY
    tables = {
        entry: [
            (entry + (3, 1, 4, 192, 168, 30, 1), 7),
            (entry + (5, 1, 4, 192, 168, 30, 1), prefix_pointer),
            (entry + (3, 2, 16) + (0,) * 16, 1),   # IPv6 row: ignored
        ],
        snmp.OID_IF_NAME: _column(snmp.OID_IF_NAME, {7: "eth1.30"}),
    }
    networks = await snmp.read_networks(FakeWalker(tables).walk)
    assert [(n.cidr, n.gateway_ip, n.vlan_id) for n in networks] == [("192.168.30.0/24", "192.168.30.1", 30)]


@pytest.mark.asyncio
async def test_snmp_without_addresses_is_an_error():
    with pytest.raises(RouterImportError, match="no IPv4 addresses"):
        await snmp.read_networks(FakeWalker({}).walk)


@pytest.mark.asyncio
async def test_snmp_optional_tables_may_fail():
    class PartialWalker(FakeWalker):
        async def walk(self, oid):
            if oid != snmp.OID_IP_ADDR_ENTRY:
                raise RouterImportError("timeout", 502)
            return UNIFI_LIKE_TABLES[oid]

    networks = await snmp.read_networks(PartialWalker().walk)
    assert [n.cidr for n in networks] == ["192.168.1.0/24", "192.168.10.0/24", "192.168.20.0/23"]
    assert all(n.name is None for n in networks)


@pytest.mark.asyncio
async def test_snmp_rejects_unknown_version():
    conn = RouterConnection(host="r", address="192.168.1.1", options={"version": "4"}, secrets={"community": "x"})
    with pytest.raises(RouterImportError) as err:
        await SnmpProvider().fetch(conn)
    assert err.value.status_code == 400


def test_snmp_v3_needs_user_and_auth_for_privacy():
    conn = RouterConnection(host="r", address="192.168.1.1", options={"version": "3"}, secrets={})
    with pytest.raises(RouterImportError, match="user name"):
        snmp.PysnmpWalker(conn)
    conn.options["username"] = "gravity"
    conn.secrets = {"priv_key": "privpass1"}
    with pytest.raises(RouterImportError, match="authentication password"):
        snmp.PysnmpWalker(conn)
    conn.secrets = {"auth_key": "authpass1", "priv_key": "privpass1"}
    snmp.PysnmpWalker(conn).close()


def test_snmp_v2c_needs_community():
    conn = RouterConnection(host="r", address="192.168.1.1", options={"version": "2c"}, secrets={})
    with pytest.raises(RouterImportError, match="community"):
        snmp.PysnmpWalker(conn)


# --- UniFi -------------------------------------------------------------------

class FakeTlsStream:
    """What httpcore hands the trace hook after the TLS handshake."""

    def __init__(self, der):
        self.der = der

    def get_extra_info(self, name):
        if name != "ssl_object":
            return None
        der = self.der

        class _Ssl:
            def getpeercert(self, binary_form=False):
                return der
        return _Ssl()


CERT_DER = b"unifi-console-certificate"
CERT_FP = certificate_fingerprint(CERT_DER)

UNIFI_NETWORKS = {
    "n-default": {"id": "n-default", "name": "Default", "vlanId": 1, "enabled": True,
                  "ipv4Configuration": {"hostIpAddress": "192.168.1.1", "prefixLength": 24}},
    "n-iot": {"id": "n-iot", "name": "IoT", "vlanId": 20, "enabled": True,
              "ipv4Configuration": {"hostIpAddress": "192.168.20.1", "prefixLength": 24,
                                    "additionalHostIpSubnets": ["192.168.21.1/24"]}},
    "n-off": {"id": "n-off", "name": "Old", "vlanId": 30, "enabled": False,
              "ipv4Configuration": {"hostIpAddress": "192.168.30.1", "prefixLength": 24}},
    "n-switch": {"id": "n-switch", "name": "Switch only", "vlanId": 40, "enabled": True},
}


def _page(items, offset, limit):
    return {"data": items[offset:offset + limit], "offset": offset, "limit": limit,
            "count": len(items[offset:offset + limit]), "totalCount": len(items)}


class FakeConsole:
    """A UniFi console behind httpx.MockTransport; runs the TLS trace hook like httpcore does."""

    def __init__(self, der=CERT_DER, sites=None, status=200, page_size=2):
        self.der = der
        self.sites = sites or [{"id": "site-1", "internalReference": "default", "name": "Default"}]
        self.status = status
        self.page_size = page_size
        self.requests = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        trace = request.extensions.get("trace")
        if trace:
            await trace("connection.start_tls.complete", {"return_value": FakeTlsStream(self.der)})
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "nope"})
        path = request.url.path
        offset = int(request.url.params.get("offset", 0))
        limit = min(int(request.url.params.get("limit", 25)), self.page_size)
        if path == f"{API_PREFIX}/sites":
            return httpx.Response(200, json=_page(self.sites, offset, limit))
        if path == f"{API_PREFIX}/sites/site-1/networks":
            overview = [{k: v for k, v in n.items() if k != "ipv4Configuration"} for n in UNIFI_NETWORKS.values()]
            return httpx.Response(200, json=_page(overview, offset, limit))
        if path.startswith(f"{API_PREFIX}/sites/site-1/networks/"):
            return httpx.Response(200, json=UNIFI_NETWORKS[path.rsplit("/", 1)[1]])
        return httpx.Response(404)


@pytest.fixture
def unifi_console(monkeypatch):
    console = FakeConsole()

    def make_client(self, conn):
        console.conn = conn
        return httpx.AsyncClient(base_url=f"https://{conn.address}", transport=httpx.MockTransport(console.handler))

    monkeypatch.setattr(UnifiProvider, "make_client", make_client)
    return console


def _unifi_conn(fingerprint=CERT_FP, **options):
    return RouterConnection(host="ucg", address="192.168.1.1", options={"fingerprint": fingerprint, **options},
                            secrets={"api_key": "secret-api-key"})


@pytest.mark.asyncio
async def test_unifi_reads_networks_across_pages(unifi_console):
    networks = await UnifiProvider().fetch(_unifi_conn())
    assert [(n.cidr, n.gateway_ip, n.vlan_id, n.name) for n in networks] == [
        ("192.168.1.0/24", "192.168.1.1", 1, "Default"),
        ("192.168.20.0/24", "192.168.20.1", 20, "IoT"),
        ("192.168.21.0/24", "192.168.21.1", 20, "IoT"),
    ]
    assert all(r.headers["X-API-KEY"] == "secret-api-key" for r in unifi_console.requests)
    # Disabled networks are not even looked up
    assert not any(r.url.path.endswith("/n-off") for r in unifi_console.requests)


@pytest.mark.asyncio
async def test_unifi_without_pin_stops_before_sending_the_key(unifi_console):
    with pytest.raises(RouterImportError) as err:
        await UnifiProvider().fetch(_unifi_conn(fingerprint=None))
    assert err.value.status_code == 409
    assert err.value.detail == {"fingerprint": CERT_FP, "reason": "untrusted_certificate"}
    assert unifi_console.requests == []


@pytest.mark.asyncio
async def test_unifi_certificate_mismatch(unifi_console):
    unifi_console.der = b"another certificate"
    with pytest.raises(RouterImportError) as err:
        await UnifiProvider().fetch(_unifi_conn())
    assert err.value.detail["reason"] == "certificate_mismatch"
    assert unifi_console.requests == []


@pytest.mark.parametrize("status, message", [
    (401, "rejected the API key"), (403, "rejected the API key"), (404, "Integration API"), (500, "HTTP 500"),
])
@pytest.mark.asyncio
async def test_unifi_http_errors(unifi_console, status, message):
    unifi_console.status = status
    with pytest.raises(RouterImportError, match=message) as err:
        await UnifiProvider().fetch(_unifi_conn())
    assert err.value.status_code == 502  # never 401: the browser would take it for its own session


@pytest.mark.asyncio
async def test_unifi_needs_api_key(unifi_console):
    conn = _unifi_conn()
    conn.secrets = {}
    with pytest.raises(RouterImportError, match="API key"):
        await UnifiProvider().fetch(conn)


def test_pick_site():
    sites = [{"id": "a", "internalReference": "default", "name": "Home"},
             {"id": "b", "internalReference": "lab", "name": "Lab"}]
    assert pick_site(sites, None)["id"] == "a"
    assert pick_site(sites, "lab")["id"] == "b"
    assert pick_site(sites, "LAB")["id"] == "b"
    with pytest.raises(RouterImportError, match="not found"):
        pick_site(sites, "office")
    with pytest.raises(RouterImportError, match="several sites"):
        pick_site([sites[1], {"id": "c", "internalReference": "x", "name": "X"}], None)


def test_normalize_fingerprint():
    hexed = "ab" * 32
    expected = ":".join(["AB"] * 32)
    assert normalize_fingerprint(hexed) == expected
    assert normalize_fingerprint(expected.lower()) == expected
    assert normalize_fingerprint(f"SHA256={hexed}") == expected
    assert normalize_fingerprint("  ") is None
    with pytest.raises(RouterImportError):
        normalize_fingerprint("abcd")


@pytest.mark.asyncio
async def test_unifi_pin_against_a_real_tls_server(tmp_path):
    """Over real TLS the pin check runs before the request: a wrong pin sends nothing, not even the key."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "unifi")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    (tmp_path / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "k.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    received = []

    async def handle(reader, writer):
        try:
            received.append(await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3))
            body = json.dumps({"data": [], "offset": 0, "limit": 200, "count": 0, "totalCount": 0}).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
                         b"Content-Length: %d\r\n\r\n" % len(body) + body)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(tmp_path / "c.pem", tmp_path / "k.pem")
    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=context)
    port = server.sockets[0].getsockname()[1]
    real_fp = certificate_fingerprint(cert.public_bytes(serialization.Encoding.DER))
    try:
        for pin in (None, ":".join(["00"] * 32)):
            conn = RouterConnection(host="ucg", address="127.0.0.1", port=port,
                                    options={"fingerprint": pin} if pin else {}, secrets={"api_key": "secret-api-key"})
            with pytest.raises(RouterImportError) as err:
                await UnifiProvider().fetch(conn)
            assert err.value.detail["fingerprint"] == real_fp
        assert received == []

        conn = RouterConnection(host="ucg", address="127.0.0.1", port=port,
                                options={"fingerprint": real_fp}, secrets={"api_key": "secret-api-key"})
        with pytest.raises(RouterImportError, match="no UniFi Network site"):
            await UnifiProvider().fetch(conn)
        assert b"secret-api-key" in received[0]
    finally:
        server.close()


@pytest.mark.asyncio
async def test_certificate_pin_trace_ignores_other_events():
    pin = CertificatePin("ucg", None)
    await pin.trace("connection.connect_tcp.complete", {"return_value": None})
    with pytest.raises(RouterImportError, match="did not present"):
        await pin.trace("connection.start_tls.complete", {"return_value": FakeTlsStream(None)})


# --- target check (SSRF) -----------------------------------------------------

@pytest.mark.parametrize("host", [
    "127.0.0.1", "169.254.169.254", "8.8.8.8", "100.64.1.1", "0.0.0.0", "::1", "fd00:ec2::254",
    "2130706433", "127.1", "localhost", "",
])
@pytest.mark.asyncio
async def test_resolve_lan_target_rejects_non_lan_hosts(host):
    with pytest.raises(RouterImportError) as err:
        await resolve_lan_target(host)
    assert err.value.status_code == 400


@pytest.mark.parametrize("host, address", [
    ("192.168.1.1", "192.168.1.1"), ("10.0.0.1", "10.0.0.1"), ("172.16.5.1", "172.16.5.1"),
    ("fd12:3456::1", "fd12:3456::1"), ("::ffff:192.168.1.1", "192.168.1.1"),
])
@pytest.mark.asyncio
async def test_resolve_lan_target_accepts_lan_addresses(host, address):
    assert await resolve_lan_target(host) == address


@pytest.mark.asyncio
async def test_resolve_lan_target_checks_every_resolved_address(monkeypatch):
    async def fake_getaddrinfo(host, port, type=0):
        return [(2, 1, 6, "", ("192.168.1.1", 0)), (2, 1, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(RouterImportError, match="not a private LAN address"):
        await resolve_lan_target("router.example")


@pytest.mark.asyncio
async def test_resolve_lan_target_uses_the_resolved_lan_address(monkeypatch):
    async def fake_getaddrinfo(host, port, type=0):
        return [(2, 1, 6, "", ("192.168.1.254", 0))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    assert await resolve_lan_target("unifi.home.arpa") == "192.168.1.254"


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "8.8.8.8", "localhost"])
@pytest.mark.asyncio
async def test_preview_refuses_non_lan_targets(client, admin_token, test_vault, snmp_router, host):
    resp = await client.post(PREVIEW, headers=_headers(admin_token), json={
        "provider": "snmp", "host": host, "secrets": {"community": "public"},
    })
    assert resp.status_code == 400
    assert snmp_router["walkers"] == []  # nothing was contacted


# --- preview / apply through the API -----------------------------------------

async def _subnets(db):
    db.expire_all()
    rows = (await db.execute(select(Subnet).order_by(Subnet.id))).scalars().all()
    return {r.cidr: (r.name, r.gateway_ip, r.vlan_id) for r in rows}


@pytest.mark.asyncio
async def test_preview_compares_without_writing(client, db, admin_token, test_vault, snmp_router):
    db.add_all([
        Subnet(cidr="192.168.1.0/24", name="Home", gateway_ip="192.168.1.254", vlan_id=None),
        Subnet(cidr="192.168.10.0/24", name="Cams", gateway_ip=None, vlan_id=None),
    ])
    await db.commit()
    before = await _subnets(db)

    resp = await client.post(PREVIEW, headers=_headers(admin_token), json={
        "provider": "snmp", "host": "192.168.1.1", "secrets": {"community": "public"},
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    by_cidr = {n["cidr"]: n for n in body["networks"]}
    assert by_cidr["192.168.1.0/24"]["status"] == "exists"            # gateway set, no VLAN to add
    assert by_cidr["192.168.1.0/24"]["fills"] == []
    assert by_cidr["192.168.10.0/24"]["status"] == "update"
    assert by_cidr["192.168.10.0/24"]["fills"] == ["gateway_ip", "vlan_id"]
    assert by_cidr["192.168.10.0/24"]["existing_name"] == "Cams"
    assert by_cidr["192.168.20.0/23"]["status"] == "new"
    assert await _subnets(db) == before
    assert snmp_router["walkers"][0].conn.address == "192.168.1.1"
    assert snmp_router["walkers"][0].closed


@pytest.mark.asyncio
async def test_preview_marks_networks_too_large_to_scan(client, admin_token, test_vault, snmp_router):
    snmp_router["tables"] = {snmp.OID_IP_ADDR_ENTRY: _ip_addr_rows([("10.0.0.1", 3, "255.0.0.0")])}
    resp = await client.post(PREVIEW, headers=_headers(admin_token), json={
        "provider": "snmp", "host": "192.168.1.1", "secrets": {"community": "public"},
    })
    assert resp.json()["networks"][0]["status"] == "too_large"


@pytest.mark.asyncio
async def test_preview_reports_router_errors(client, admin_token, test_vault, snmp_router):
    snmp_router["error"] = "No valid SNMP answer from 192.168.1.1: timeout"
    resp = await client.post(PREVIEW, headers=_headers(admin_token), json={
        "provider": "snmp", "host": "192.168.1.1", "secrets": {"community": "wrong"},
    })
    assert resp.status_code == 502
    assert "No valid SNMP answer" in resp.json()["detail"]
    assert "wrong" not in resp.text


@pytest.mark.asyncio
async def test_apply_adds_and_only_fills_empty_fields(client, db, admin_token):
    db.add_all([
        Subnet(cidr="192.168.1.0/24", name="Home", gateway_ip="192.168.1.254", vlan_id=5),
        Subnet(cidr="192.168.10.0/24", name="Cams", gateway_ip=None, vlan_id=None),
        Subnet(cidr="192.168.11.0/24", name="Keep", gateway_ip=None, vlan_id=11),
    ])
    await db.commit()

    resp = await client.post(APPLY, headers=_headers(admin_token), json={"networks": [
        {"cidr": "192.168.1.0/24", "name": "br0", "gateway_ip": "192.168.1.1", "vlan_id": 1},
        {"cidr": "192.168.10.0/24", "name": "Kameras", "gateway_ip": "192.168.10.1", "vlan_id": 10},
        {"cidr": "192.168.11.0/24", "name": "x", "gateway_ip": "192.168.11.1", "vlan_id": 99},
        {"cidr": "192.168.20.0/23", "name": "IoT", "gateway_ip": "192.168.20.1", "vlan_id": 20},
    ]})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "added": ["192.168.20.0/23"],
        "updated": ["192.168.10.0/24", "192.168.11.0/24"],
        "unchanged": ["192.168.1.0/24"],
    }
    assert await _subnets(db) == {
        "192.168.1.0/24": ("Home", "192.168.1.254", 5),      # nothing overwritten
        "192.168.10.0/24": ("Cams", "192.168.10.1", 10),     # name kept, empty fields filled
        "192.168.11.0/24": ("Keep", "192.168.11.1", 11),     # VLAN kept, gateway filled
        "192.168.20.0/23": ("IoT", "192.168.20.1", 20),
    }


@pytest.mark.asyncio
async def test_apply_matches_existing_rows_in_canonical_form(client, db, admin_token):
    db.add(Subnet(cidr="192.168.10.5/24", name="Legacy", gateway_ip=None, vlan_id=None))
    await db.commit()
    resp = await client.post(APPLY, headers=_headers(admin_token), json={"networks": [
        {"cidr": "192.168.10.0/24", "gateway_ip": "192.168.10.1", "vlan_id": 10},
    ]})
    assert resp.json()["updated"] == ["192.168.10.0/24"]
    assert await _subnets(db) == {"192.168.10.5/24": ("Legacy", "192.168.10.1", 10)}


@pytest.mark.parametrize("item", [
    {"cidr": "10.0.0.0/8"},                                         # too large to scan
    {"cidr": "192.168.1.0/24", "gateway_ip": "192.168.2.1"},        # gateway outside
    {"cidr": "192.168.1.0/24", "vlan_id": 5000},
    {"cidr": "not-a-net"},
])
@pytest.mark.asyncio
async def test_apply_validates(client, db, admin_token, item):
    resp = await client.post(APPLY, headers=_headers(admin_token), json={"networks": [item]})
    assert resp.status_code == 422
    assert await _subnets(db) == {}


@pytest.mark.asyncio
async def test_apply_without_a_new_name_uses_the_default(client, db, admin_token):
    resp = await client.post(APPLY, headers=_headers(admin_token), json={"networks": [{"cidr": "192.168.40.0/24"}]})
    assert resp.status_code == 200
    assert await _subnets(db) == {"192.168.40.0/24": ("Network 192.168.40.0/24", None, None)}


# --- credentials ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_credentials_are_stored_encrypted_and_never_returned(client, db, admin_token, test_vault, unifi_console):
    resp = await client.post(PREVIEW, headers=_headers(admin_token), json={
        "provider": "unifi", "host": "192.168.1.1",
        "options": {"fingerprint": CERT_FP.lower(), "site": "", "bogus": "dropped"},
        "secrets": {"api_key": "secret-api-key"},
    })
    assert resp.status_code == 200, resp.text
    assert "secret-api-key" not in resp.text

    row = (await db.execute(select(RouterImportSource))).scalar_one()
    assert "secret-api-key" not in row.encrypted_secrets
    assert json.loads(test_vault.decrypt(row.encrypted_secrets)) == {"api_key": "secret-api-key"}

    sources = await client.get(SOURCES, headers=_headers(admin_token))
    assert sources.json() == [{
        "provider": "unifi", "host": "192.168.1.1", "port": None,
        "options": {"fingerprint": CERT_FP}, "stored_secrets": ["api_key"],
    }]
    assert "secret-api-key" not in sources.text

    # A second fetch from the same router reuses the stored key
    unifi_console.requests.clear()
    again = await client.post(PREVIEW, headers=_headers(admin_token), json={
        "provider": "unifi", "host": "192.168.1.1", "options": {"fingerprint": CERT_FP},
    })
    assert again.status_code == 200, again.text
    assert unifi_console.requests[0].headers["X-API-KEY"] == "secret-api-key"


@pytest.mark.asyncio
async def test_stored_secret_is_not_sent_to_another_router(client, db, admin_token, test_vault, unifi_console):
    db.add(RouterImportSource(provider="unifi", host="192.168.1.1", options="{}",
                              encrypted_secrets=test_vault.encrypt(json.dumps({"api_key": "secret-api-key"}))))
    await db.commit()
    resp = await client.post(PREVIEW, headers=_headers(admin_token), json={
        "provider": "unifi", "host": "192.168.1.2", "options": {"fingerprint": CERT_FP},
    })
    assert resp.status_code == 400
    assert "API key" in resp.json()["detail"]
    assert unifi_console.requests == []


@pytest.mark.asyncio
async def test_unconfirmed_certificate_is_a_preview_state(client, db, admin_token, test_vault, unifi_console):
    resp = await client.post(PREVIEW, headers=_headers(admin_token), json={
        "provider": "unifi", "host": "192.168.1.1", "secrets": {"api_key": "secret-api-key"},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirm_certificate"
    assert body["fingerprint"] == CERT_FP
    assert body["networks"] == []
    assert unifi_console.requests == []
    # Nothing is remembered before the fetch succeeded
    assert (await db.execute(select(RouterImportSource))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_remember_false_stores_nothing(client, db, admin_token, test_vault, snmp_router):
    resp = await client.post(PREVIEW, headers=_headers(admin_token), json={
        "provider": "snmp", "host": "192.168.1.1", "secrets": {"community": "public"}, "remember": False,
    })
    assert resp.status_code == 200
    assert (await db.execute(select(RouterImportSource))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_source(client, db, admin_token, test_vault, snmp_router):
    await client.post(PREVIEW, headers=_headers(admin_token), json={
        "provider": "snmp", "host": "192.168.1.1", "options": {"version": "2c"}, "secrets": {"community": "public"},
    })
    assert (await client.delete(f"{SOURCES}/snmp", headers=_headers(admin_token))).status_code == 200
    assert (await client.get(SOURCES, headers=_headers(admin_token))).json() == []
    assert (await client.delete(f"{SOURCES}/snmp", headers=_headers(admin_token))).status_code == 404


@pytest.mark.asyncio
async def test_router_import_requires_authentication(client, admin_token):
    assert (await client.get(SOURCES)).status_code == 401
    assert (await client.post(PREVIEW, json={"provider": "snmp", "host": "192.168.1.1"})).status_code == 401
    assert (await client.post(APPLY, json={"networks": [{"cidr": "192.168.1.0/24"}]})).status_code == 401


def test_base_lan_address_rules():
    assert base.is_lan_address(ipaddress.ip_address("192.168.1.1"))
    assert not base.is_lan_address(ipaddress.ip_address("127.0.0.1"))
    assert not base.is_lan_address(ipaddress.ip_address("100.64.0.1"))
