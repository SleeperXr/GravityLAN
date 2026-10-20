"""Router import over SNMP (v1/v2c/v3, read-only): works with most routers and firewalls.

The router's own interface addresses and masks (IP-MIB ipAddrTable, or the newer
ipAddressTable) give each network together with its gateway. IF-MIB ifName/ifAlias
names the interface; the VLAN ID comes from interface names such as br10, eth0.10,
vlan10 or igb1_vlan10, and Q-BRIDGE-MIB supplies a VLAN's name when the router has one.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.router_import.base import RouterConnection, RouterImportError, RouterNetwork, RouterProvider

logger = logging.getLogger(__name__)

OID_IP_ADDR_ENTRY = (1, 3, 6, 1, 2, 1, 4, 20, 1)        # ipAddrTable: .2 ifIndex, .3 netmask
OID_IP_ADDRESS_ENTRY = (1, 3, 6, 1, 2, 1, 4, 34, 1)     # ipAddressTable: .3 ifIndex, .5 prefix
OID_IF_DESCR = (1, 3, 6, 1, 2, 1, 2, 2, 1, 2)
OID_IF_NAME = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 1)
OID_IF_ALIAS = (1, 3, 6, 1, 2, 1, 31, 1, 1, 1, 18)
OID_VLAN_STATIC_NAME = (1, 3, 6, 1, 2, 1, 17, 7, 1, 4, 3, 1, 1)  # Q-BRIDGE dot1qVlanStaticName

# Rows read per table at most; a router has a few dozen, this only stops a runaway walk
MAX_ROWS = 5000

Oid = tuple[int, ...]
Rows = list[tuple[Oid, Any]]
Walk = Callable[[Oid], Awaitable[Rows]]

_VLAN_PATTERNS = (
    re.compile(r"[._]vlan[._-]?(\d{1,4})$", re.I),           # igb1_vlan10, eth0.vlan10
    re.compile(r"\.(\d{1,4})$"),                              # eth0.10, switch0.10, vlan0.10
    re.compile(r"^(?:br|vlan|vl|bridge|irb|vlanif|vlan-interface)[._-]?(\d{1,4})$", re.I),  # br10, Vlan10, irb.10
)


def parse_vlan_id(name: str | None) -> int | None:
    """The VLAN ID an interface name carries (br10, eth0.10, vlan10, igb1_vlan10), else None.

    br0 and other names ending in 0 carry no VLAN: 0 is not a valid VLAN ID.
    """
    if not name:
        return None
    name = name.strip()
    for pattern in _VLAN_PATTERNS:
        match = pattern.search(name)
        if match:
            vlan = int(match.group(1))
            return vlan if 1 <= vlan <= 4094 else None
    return None


def _split(rows: Rows, base: Oid) -> dict[Oid, dict[int, Any]]:
    """Table rows grouped by row index: {index: {column: value}}."""
    table: dict[Oid, dict[int, Any]] = {}
    size = len(base)
    for oid, value in rows:
        if tuple(oid[:size]) != base or len(oid) <= size + 1:
            continue
        table.setdefault(tuple(oid[size + 1:]), {})[oid[size]] = value
    return table


def _column(rows: Rows, base: Oid) -> dict[int, Any]:
    """A single-index column such as ifName: {ifIndex: value}."""
    size = len(base)
    return {oid[size]: value for oid, value in rows if tuple(oid[:size]) == base and len(oid) == size + 1}


def _ipv4(value: Any) -> ipaddress.IPv4Address | None:
    try:
        if isinstance(value, (bytes, bytearray)) and len(value) == 4:
            return ipaddress.IPv4Address(bytes(value))
        return ipaddress.IPv4Address(str(value))
    except ValueError:
        return None


def addresses_from_ip_addr_table(rows: Rows) -> list[tuple[ipaddress.IPv4Address, int, int | None]]:
    """(address, prefix length, ifIndex) from ipAddrTable rows."""
    found = []
    for index, cols in _split(rows, OID_IP_ADDR_ENTRY).items():
        addr = _ipv4(cols.get(1)) or (_ipv4(".".join(map(str, index))) if len(index) == 4 else None)
        mask = _ipv4(cols.get(3))
        if addr is None or mask is None:
            continue
        try:
            prefix = ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
        except ValueError:
            continue
        if_index = cols.get(2)
        found.append((addr, prefix, int(if_index) if if_index is not None else None))
    return found


def addresses_from_ip_address_table(rows: Rows) -> list[tuple[ipaddress.IPv4Address, int, int | None]]:
    """(address, prefix length, ifIndex) of the IPv4 rows of ipAddressTable.

    The index is addressType.length.address (1.4.a.b.c.d; some agents drop the length);
    the prefix length is the last sub-identifier of the ipAddressPrefix row pointer.
    """
    found = []
    for index, cols in _split(rows, OID_IP_ADDRESS_ENTRY).items():
        if not index or index[0] != 1 or len(index) < 5:
            continue
        addr = _ipv4(".".join(map(str, index[-4:])))
        pointer = cols.get(5)
        if addr is None or not pointer:
            continue
        try:
            prefix = int(tuple(pointer)[-1])
        except (TypeError, ValueError, IndexError):
            continue
        if not 0 < prefix <= 32:
            continue
        if_index = cols.get(3)
        found.append((addr, prefix, int(if_index) if if_index is not None else None))
    return found


def build_networks(
    addresses: list[tuple[ipaddress.IPv4Address, int, int | None]],
    if_names: dict[int, str],
    if_aliases: dict[int, str],
    if_descrs: dict[int, str],
    vlan_names: dict[int, str],
) -> list[RouterNetwork]:
    """The router's LAN networks: private, not loopback/link-local, larger than a /31."""
    networks: list[RouterNetwork] = []
    seen: set[str] = set()
    for addr, prefix, if_index in addresses:
        if not addr.is_private or addr.is_loopback or addr.is_link_local or prefix > 30:
            continue
        cidr = str(ipaddress.IPv4Network(f"{addr}/{prefix}", strict=False))
        if cidr in seen:
            continue
        seen.add(cidr)
        if_name = (if_names.get(if_index) or if_descrs.get(if_index) or "").strip() or None
        vlan_id = parse_vlan_id(if_name) or parse_vlan_id(if_descrs.get(if_index))
        alias = (if_aliases.get(if_index) or "").strip()
        name = alias or (vlan_names.get(vlan_id, "").strip() if vlan_id else "") or if_name
        networks.append(RouterNetwork(cidr=cidr, gateway_ip=str(addr), name=name or None, vlan_id=vlan_id, interface=if_name))
    return networks


async def read_networks(walk: Walk) -> list[RouterNetwork]:
    """Ask a router through ``walk`` (one table per call) and return its networks."""
    addresses = addresses_from_ip_addr_table(await walk(OID_IP_ADDR_ENTRY))
    if not addresses:
        addresses = addresses_from_ip_address_table(await walk(OID_IP_ADDRESS_ENTRY))
    if not addresses:
        raise RouterImportError(
            "The router answered over SNMP but reported no IPv4 addresses (IP-MIB ipAddrTable/ipAddressTable).",
            502,
        )
    texts = {}
    for oid in (OID_IF_NAME, OID_IF_ALIAS, OID_IF_DESCR, OID_VLAN_STATIC_NAME):
        try:
            texts[oid] = {k: str(v) for k, v in _column(await walk(oid), oid).items()}
        except RouterImportError as err:
            # Optional tables: a router without IF-MIB/Q-BRIDGE-MIB still yields its networks
            logger.debug("Router import: SNMP table %s unavailable: %s", ".".join(map(str, oid)), err.message)
            texts[oid] = {}
    return build_networks(addresses, texts[OID_IF_NAME], texts[OID_IF_ALIAS], texts[OID_IF_DESCR], texts[OID_VLAN_STATIC_NAME])


# --- pysnmp transport -------------------------------------------------------

_AUTH_PROTOCOLS = {
    "MD5": "usmHMACMD5AuthProtocol",
    "SHA": "usmHMACSHAAuthProtocol",
    "SHA224": "usmHMAC128SHA224AuthProtocol",
    "SHA256": "usmHMAC192SHA256AuthProtocol",
    "SHA384": "usmHMAC256SHA384AuthProtocol",
    "SHA512": "usmHMAC384SHA512AuthProtocol",
}
_PRIV_PROTOCOLS = {
    "DES": "usmDESPrivProtocol",
    "3DES": "usm3DESEDEPrivProtocol",
    "AES": "usmAesCfb128Protocol",
    "AES192": "usmAesCfb192Protocol",
    "AES256": "usmAesCfb256Protocol",
}
SNMP_VERSIONS = ("1", "2c", "3")


def _to_python(value: Any) -> Any:
    """A pysnmp value as plain Python: address text, OID tuple, decoded string or int."""
    kind = type(value).__name__
    if kind == "IpAddress":
        return str(ipaddress.IPv4Address(bytes(value.asOctets())))
    if kind == "ObjectIdentifier":
        return tuple(value)
    if hasattr(value, "asOctets"):
        return bytes(value.asOctets()).decode("utf-8", "replace").rstrip("\x00")
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


class PysnmpWalker:
    """Walks tables of one router with pysnmp (pure Python, no net-snmp needed)."""

    def __init__(self, conn: RouterConnection, timeout: float = 3.0, retries: int = 1):
        from pysnmp.hlapi.v3arch import asyncio as hlapi

        self._hlapi = hlapi
        self._conn = conn
        self._timeout = timeout
        self._retries = retries
        self._engine = hlapi.SnmpEngine()
        self._target = None
        self._auth = self._auth_data()

    def _auth_data(self):
        hlapi = self._hlapi
        options, secrets = self._conn.options, self._conn.secrets
        version = str(options.get("version") or "2c")
        if version in ("1", "2c"):
            community = secrets.get("community") or ""
            if not community:
                raise RouterImportError("Enter the SNMP community.", 400)
            return hlapi.CommunityData(community, mpModel=0 if version == "1" else 1)
        user = (options.get("username") or "").strip()
        if not user:
            raise RouterImportError("Enter the SNMPv3 user name.", 400)
        auth_key, priv_key = secrets.get("auth_key") or None, secrets.get("priv_key") or None
        if priv_key and not auth_key:
            raise RouterImportError("SNMPv3 encryption (privacy) needs an authentication password as well.", 400)
        kwargs = {}
        if auth_key:
            kwargs["authProtocol"] = getattr(hlapi, _AUTH_PROTOCOLS[str(options.get("auth_protocol") or "SHA")])
        if priv_key:
            kwargs["privProtocol"] = getattr(hlapi, _PRIV_PROTOCOLS[str(options.get("priv_protocol") or "AES")])
        return hlapi.UsmUserData(user, authKey=auth_key, privKey=priv_key, **kwargs)

    async def walk(self, base: Oid) -> Rows:
        hlapi = self._hlapi
        if self._target is None:
            self._target = await hlapi.UdpTransportTarget.create(
                (self._conn.address, self._conn.port or SnmpProvider.default_port),
                timeout=self._timeout, retries=self._retries,
            )
        rows: Rows = []
        async for err_indication, err_status, _err_index, var_binds in hlapi.walk_cmd(
            self._engine, self._auth, self._target, hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity(".".join(map(str, base)))),
            lexicographicMode=False, lookupMib=False,
        ):
            if err_indication:
                raise RouterImportError(
                    f"No valid SNMP answer from {self._conn.host}: {err_indication}. "
                    "Check that SNMP is enabled, UDP port 161 is reachable and the credentials match.",
                    502,
                )
            if err_status:
                break  # v1 noSuchName at the end of the table, or the agent refuses this table
            for oid, value in var_binds:
                if type(value).__name__ in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"):
                    continue
                rows.append((tuple(oid), _to_python(value)))
            if len(rows) >= MAX_ROWS:
                break
        return rows

    def close(self) -> None:
        try:
            self._engine.close_dispatcher()
        except Exception:  # pragma: no cover - best effort cleanup
            pass


class SnmpProvider(RouterProvider):
    key = "snmp"
    default_port = 161
    secret_fields = ("community", "auth_key", "priv_key")
    option_fields = ("version", "username", "auth_protocol", "priv_protocol")

    def open_walker(self, conn: RouterConnection) -> PysnmpWalker:
        return PysnmpWalker(conn)

    async def fetch(self, conn: RouterConnection) -> list[RouterNetwork]:
        version = str(conn.options.get("version") or "2c")
        if version not in SNMP_VERSIONS:
            raise RouterImportError(f"Unknown SNMP version '{version}'. Use 1, 2c or 3.", 400)
        if str(conn.options.get("auth_protocol") or "SHA") not in _AUTH_PROTOCOLS:
            raise RouterImportError("Unknown SNMPv3 authentication protocol.", 400)
        if str(conn.options.get("priv_protocol") or "AES") not in _PRIV_PROTOCOLS:
            raise RouterImportError("Unknown SNMPv3 privacy protocol.", 400)
        walker = self.open_walker(conn)
        try:
            return await read_networks(walker.walk)
        finally:
            walker.close()
