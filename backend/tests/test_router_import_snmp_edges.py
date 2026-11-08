"""Edges of the SNMP router import (app/services/router_import/snmp.py): malformed table rows,
pysnmp value conversion, SNMPv1/v2c/v3 credentials, the walk loop and the provider's option checks.
pysnmp is replaced by a small fake module; nothing is sent on the network."""

import ipaddress
from types import SimpleNamespace

import pytest

import app.services.router_import.snmp as snmp
from app.services.router_import.base import RouterConnection, RouterImportError

ENTRY = snmp.OID_IP_ADDR_ENTRY
ADDRESS = snmp.OID_IP_ADDRESS_ENTRY


# --- table parsing --------------------------------------------------------------------------

def test_split_and_column_skip_foreign_and_short_rows():
    rows = [((*ENTRY,), "too short"), ((1, 3, 6, 9), "other table"), ((*ENTRY, 1, 192, 0, 2, 1), "ok")]
    assert snmp._split(rows, ENTRY) == {(192, 0, 2, 1): {1: "ok"}}
    column = [((*snmp.OID_IF_NAME, 5), "eth0"), ((*snmp.OID_IF_NAME, 5, 1), "x")]
    assert snmp._column(column, snmp.OID_IF_NAME) == {5: "eth0"}


def test_ipv4_from_bytes_text_or_garbage():
    assert snmp._ipv4(b"\xc0\x00\x02\x01") == ipaddress.IPv4Address("192.0.2.1")
    assert snmp._ipv4("192.0.2.1") == ipaddress.IPv4Address("192.0.2.1")
    assert snmp._ipv4("not an ip") is None


def test_ip_addr_table_skips_bad_masks_and_reads_the_index():
    rows = [
        # address only in the index, no ifIndex column
        ((*ENTRY, 3, 192, 0, 2, 1), "255.255.255.0"),
        # no mask at all
        ((*ENTRY, 1, 198, 51, 100, 1), "198.51.100.1"),
        # a mask that is no prefix
        ((*ENTRY, 1, 203, 0, 113, 1), "203.0.113.1"),
        ((*ENTRY, 3, 203, 0, 113, 1), "255.0.255.0"),
    ]
    assert snmp.addresses_from_ip_addr_table(rows) == [(ipaddress.IPv4Address("192.0.2.1"), 24, None)]


def test_ip_address_table_skips_bad_rows():
    rows = [
        ((*ADDRESS, 5, 2, 16, 1, 2, 3, 4), (1, 2, 64)),  # IPv6 (type 2)
        ((*ADDRESS, 5, 1, 4, 10, 0, 0, 1), None),  # no prefix pointer
        ((*ADDRESS, 5, 1, 4, 10, 0, 1, 1), ("x",)),  # pointer that ends in no number
        ((*ADDRESS, 5, 1, 4, 10, 0, 2, 1), (1, 2, 40)),  # prefix out of range
        ((*ADDRESS, 5, 1, 4, 10, 0, 3, 1), (1, 2, 24)),
    ]
    assert snmp.addresses_from_ip_address_table(rows) == [(ipaddress.IPv4Address("10.0.3.1"), 24, None)]


def test_build_networks_keeps_each_network_once():
    addr = ipaddress.IPv4Address
    networks = snmp.build_networks([(addr("192.0.2.1"), 24, 1), (addr("192.0.2.2"), 24, 2)], {1: "br0"}, {}, {}, {})
    assert [n.cidr for n in networks] == ["192.0.2.0/24"]


# --- pysnmp values ---------------------------------------------------------------------------

def _value(kind, **attrs):
    return type(kind, (), attrs)()


def test_to_python_conversions():
    assert snmp._to_python(_value("IpAddress", asOctets=lambda self: b"\xc0\x00\x02\x01")) == "192.0.2.1"

    class ObjectIdentifier(tuple):
        pass

    assert snmp._to_python(ObjectIdentifier((1, 3, 6))) == (1, 3, 6)
    assert snmp._to_python(_value("OctetString", asOctets=lambda self: b"WAN\x00")) == "WAN"
    assert snmp._to_python(7) == 7
    assert snmp._to_python(_value("Opaque")).startswith("<")  # neither int nor octets: its text


# --- credentials and walk with a fake pysnmp -----------------------------------------------------

class FakeHlapi:
    usmHMACSHAAuthProtocol = "SHA"
    usmHMAC192SHA256AuthProtocol = "SHA256"
    usmAesCfb128Protocol = "AES"
    usmDESPrivProtocol = "DES"

    def __init__(self, answers=()):
        self.answers = list(answers)

    def CommunityData(self, community, mpModel):
        return ("community", community, mpModel)

    def UsmUserData(self, user, authKey=None, privKey=None, **kw):
        return ("usm", user, authKey, privKey, kw)

    class UdpTransportTarget:
        @staticmethod
        async def create(addr, timeout, retries):
            return ("target", addr)

    def ContextData(self):
        return None

    def ObjectIdentity(self, oid):
        return oid

    def ObjectType(self, identity):
        return identity

    async def walk_cmd(self, *args, **kwargs):
        for answer in self.answers:
            yield answer


def walker(options=None, secrets=None, answers=()):
    w = object.__new__(snmp.PysnmpWalker)
    w._hlapi = FakeHlapi(answers)
    w._conn = RouterConnection(host="router.lan", address="192.0.2.1", options=options or {}, secrets=secrets or {})
    w._timeout, w._retries, w._target = 1.0, 0, None
    w._engine = SimpleNamespace(close_dispatcher=lambda: None)
    return w


def test_v1_and_v2c_need_a_community():
    assert walker({"version": "1"}, {"community": "public"})._auth_data() == ("community", "public", 0)
    assert walker({}, {"community": "public"})._auth_data() == ("community", "public", 1)
    with pytest.raises(RouterImportError, match="community"):
        walker({"version": "2c"}, {})._auth_data()


def test_v3_credentials():
    assert walker({"version": "3", "username": " admin "}, {})._auth_data() == ("usm", "admin", None, None, {})
    options = {"version": "3", "username": "admin", "auth_protocol": "SHA256", "priv_protocol": "DES"}
    full = walker(options, {"auth_key": "a" * 8, "priv_key": "p" * 8})
    assert full._auth_data() == ("usm", "admin", "a" * 8, "p" * 8, {"authProtocol": "SHA256", "privProtocol": "DES"})
    with pytest.raises(RouterImportError, match="user name"):
        walker({"version": "3"}, {})._auth_data()
    with pytest.raises(RouterImportError, match="authentication password"):
        walker({"version": "3", "username": "admin"}, {"priv_key": "p" * 8})._auth_data()


async def test_walk_collects_rows_and_skips_missing_objects():
    missing = type("NoSuchInstance", (), {})()
    answers = [
        (None, 0, 0, [((1, 3, 6, 1), 5), ((1, 3, 6, 2), missing)]),
        (None, 0, 0, [((1, 3, 6, 3), 7)]),
        (None, 2, 0, []),  # error status ends the table
        (None, 0, 0, [((1, 3, 6, 4), 9)]),
    ]
    w = walker({}, {"community": "public"}, answers)
    w._auth = w._auth_data()
    assert await w.walk((1, 3, 6)) == [((1, 3, 6, 1), 5), ((1, 3, 6, 3), 7)]
    assert w._target == ("target", ("192.0.2.1", 161))


async def test_walk_reports_no_answer_and_stops_at_the_row_limit(monkeypatch):
    w = walker({}, {"community": "public"}, [("requestTimedOut", 0, 0, [])])
    w._auth = w._auth_data()
    with pytest.raises(RouterImportError, match="No valid SNMP answer from router.lan: requestTimedOut"):
        await w.walk((1, 3, 6))

    monkeypatch.setattr(snmp, "MAX_ROWS", 2)
    many = [(None, 0, 0, [((1, 3, 6, i), i)]) for i in range(5)]
    w = walker({}, {"community": "public"}, many)
    w._auth = w._auth_data()
    assert len(await w.walk((1, 3, 6))) == 2


# --- provider ------------------------------------------------------------------------------

@pytest.mark.parametrize("options, message", [
    ({"version": "4"}, "Unknown SNMP version '4'"),
    ({"auth_protocol": "MD4"}, "authentication protocol"),
    ({"priv_protocol": "ROT13"}, "privacy protocol"),
])
async def test_provider_rejects_unknown_options(options, message):
    conn = RouterConnection(host="router.lan", address="192.0.2.1", options=options, secrets={"community": "public"})
    with pytest.raises(RouterImportError, match=message):
        await snmp.SnmpProvider().fetch(conn)


async def test_provider_reads_networks_and_closes_the_walker():
    closed = []

    class Walker:
        async def walk(self, oid):
            if oid == snmp.OID_IP_ADDR_ENTRY:
                return [((*ENTRY, 1, 192, 168, 10, 1), "192.168.10.1"), ((*ENTRY, 3, 192, 168, 10, 1), "255.255.255.0")]
            return []

        def close(self):
            closed.append(True)

    provider = snmp.SnmpProvider()
    provider.open_walker = lambda conn: Walker()
    conn = RouterConnection(host="router.lan", address="192.0.2.1", secrets={"community": "public"})
    networks = await provider.fetch(conn)
    assert [n.cidr for n in networks] == ["192.168.10.0/24"]
    assert closed == [True]
