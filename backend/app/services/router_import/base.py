"""Common ground of the router import providers.

A provider asks one router for the networks it routes and returns them as
RouterNetwork entries. It never writes anything: the import service turns the
list into a preview and only the networks the admin picks reach the Subnet table.

Providers for more router families (OPNsense/pfSense REST, FRITZ!Box TR-064,
OpenWrt ubus, ...) plug in by subclassing RouterProvider and registering in
app.services.router_import.PROVIDERS.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.schemas.webhook import is_blocked_webhook_ip


class RouterImportError(Exception):
    """A router could not be asked; ``message`` is safe to show (it never contains secrets)."""

    def __init__(self, message: str, status_code: int = 502, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}


@dataclass
class RouterNetwork:
    """One network the router routes: its address range and the router's own address in it."""

    cidr: str
    gateway_ip: str | None = None
    name: str | None = None
    vlan_id: int | None = None
    interface: str | None = None


@dataclass
class RouterConnection:
    """Where and how to reach a router. ``address`` is the checked IP the provider must connect to."""

    host: str
    address: str
    port: int | None = None
    options: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)


class RouterProvider:
    """A way to read the networks of a router."""

    key: ClassVar[str]
    default_port: ClassVar[int]
    # Fields of ``secrets`` this provider uses; only these are stored (encrypted)
    secret_fields: ClassVar[tuple[str, ...]] = ()
    # Fields of ``options`` this provider uses; anything else is dropped
    option_fields: ClassVar[tuple[str, ...]] = ()

    async def fetch(self, conn: RouterConnection) -> list[RouterNetwork]:
        raise NotImplementedError


def is_lan_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for addresses a router import may contact: private LAN space only.

    Loopback (GravityLAN itself), link-local, the cloud metadata endpoints and
    public or carrier-grade NAT addresses are refused, so the import cannot be
    pointed at the host, the cloud provider or the internet.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private and not is_blocked_webhook_ip(ip)


async def resolve_lan_target(host: str) -> str:
    """The private address to contact for ``host``, or RouterImportError (400) when it is none.

    A host name must resolve to LAN addresses only; the provider then connects to the
    returned address, so a second lookup cannot swap in another target (DNS rebinding).
    """
    host = (host or "").strip().strip("[]").rstrip(".")
    if not host:
        raise RouterImportError("Enter the router's address.", 400)
    try:
        return _checked(ipaddress.ip_address(host), host)
    except ValueError:
        pass
    last_label = host.rsplit(".", 1)[-1]
    if last_label.isdigit() or last_label.lower().startswith("0x"):
        # Numeric forms such as 2130706433 or 127.1 that resolvers still read as an address
        raise RouterImportError("Use a dotted IPv4 address or a host name.", 400)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise RouterImportError(f"The host name {host} could not be resolved.", 400) from None
    addresses = []
    for *_, sockaddr in infos:
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0].split("%", 1)[0]))
        except ValueError:
            continue
    if not addresses:
        raise RouterImportError(f"The host name {host} could not be resolved.", 400)
    for addr in addresses:
        _checked(addr, host)
    ipv4 = [a for a in addresses if a.version == 4]
    return str((ipv4 or addresses)[0])


def _checked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, host: str) -> str:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not is_lan_address(ip):
        raise RouterImportError(
            f"{host} is not a private LAN address. The router import only contacts routers in the local network.",
            400,
        )
    return str(ip)
