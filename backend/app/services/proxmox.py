"""Read-only Proxmox VE discovery: guest names and addresses, no guest operations.

Ported from the PedanXr fork (feat/proxmox-integration, author Daniel Schulze).
"""
import asyncio
import ipaddress
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from sqlalchemy import select, update

from app.models.device import Device, DiscoveredHost
from app.models.proxmox import ProxmoxIntegration
from app.scanner.hostname import is_ip_like
from app.services.cache_service import dashboard_cache, discovery_cache, topology_cache
from app.services.secret_vault import VaultError, vault


# One sync at a time (manual or scheduled); it may wait up to two minutes on Proxmox.
sync_lock = asyncio.Lock()
# Settings changes and applying a sync result. Held only briefly, so saving the settings
# never waits for a slow Proxmox server. In-process locks: GravityLAN runs a single worker.
write_lock = asyncio.Lock()

DISCOVERY_TIMEOUT_SECONDS = 120


class ProxmoxError(Exception):
    """A safe, credential-free error suitable for the settings UI."""


@dataclass
class Guest:
    identity: str  # "qemu/100" or "lxc/101"
    name: str
    addresses: list[str]


def _inventory(connection: ProxmoxIntegration) -> dict:
    try:
        data = json.loads(connection.inventory or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def imported_addresses(db) -> set[str]:
    """Addresses of the last sync; they stay listed even before a network probe reaches them."""
    connection = await db.get(ProxmoxIntegration, 1)
    if not connection or not connection.enabled:
        return set()
    return set(_inventory(connection))


def usable_ip(value: str) -> str | None:
    """The address of an interface entry, or None for loopback, link-local, multicast and unspecified."""
    try:
        addr = ipaddress.ip_interface(value.strip()).ip
    except ValueError:
        return None
    if addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_unspecified:
        return None
    return str(addr)


class ProxmoxClient:
    """GET-only client for the Proxmox VE API with an API token."""

    def __init__(self, url: str, token_id: str, secret: str, verify_tls: bool = True):
        self.client = httpx.AsyncClient(
            base_url=url + "/api2/json/",
            headers={"Authorization": f"PVEAPIToken={token_id}={secret}"},
            verify=verify_tls, follow_redirects=False, timeout=10.0,
        )

    async def get(self, path: str):
        try:
            response = await self.client.get(path)
            if response.status_code in (401, 403):
                raise ProxmoxError("Proxmox denied access. Check the API token and its permissions.")
            if response.status_code != 200:
                raise ProxmoxError(f"Proxmox returned HTTP {response.status_code}.")
            return response.json()["data"]
        except httpx.TransportError as exc:
            raise ProxmoxError("Cannot connect to Proxmox. Check the address, network and TLS certificate.") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise ProxmoxError("Proxmox returned an invalid API response.") from exc

    async def _guest_addresses(self, prefix: str, kind: str, running: bool) -> list:
        if kind == "qemu":
            data = await self.get(prefix + "/agent/network-get-interfaces")
            return [a.get("ip-address", "") for i in data.get("result", []) for a in i.get("ip-addresses", [])]
        if running:
            interfaces = await self.get(prefix + "/interfaces")
            addresses = [i.get(key, "") for i in interfaces for key in ("inet", "inet6")]
            addresses.extend(a.get("ip-address", "") for i in interfaces for a in i.get("ip-addresses", []))
            return addresses
        # Static LXC addresses are known while the container is stopped; DHCP ones are not.
        config = await self.get(prefix + "/config")
        return [part.split("=", 1)[1] for key, value in config.items()
                if key.startswith("net") and key[3:].isdigit() and isinstance(value, str)
                for part in value.split(",") if part.startswith(("ip=", "ip6="))]

    async def discover(self) -> tuple[list[Guest], int]:
        """All VMs and containers with at least one usable address, and the number skipped."""
        resources = await self.get("cluster/resources?type=vm")
        if not isinstance(resources, list):
            raise ProxmoxError("Proxmox returned an invalid guest list.")
        semaphore = asyncio.Semaphore(4)

        async def read_guest(resource) -> tuple[Guest | None, bool]:
            if not isinstance(resource, dict) or resource.get("type") not in ("qemu", "lxc") or resource.get("template"):
                return None, False
            name = str(resource.get("name") or "").strip()[:100]
            node = resource.get("node")
            vmid = resource.get("vmid")
            if not name or not node or not isinstance(vmid, int):
                return None, True
            kind = resource["type"]
            running = resource.get("status") == "running"
            # A stopped VM has no guest agent to ask; never reuse stale agent data.
            if kind == "qemu" and not running:
                return None, True
            prefix = f"nodes/{quote(str(node), safe='')}/{kind}/{vmid}"
            async with semaphore:
                try:
                    addresses = await self._guest_addresses(prefix, kind, running)
                except (ProxmoxError, TypeError, AttributeError, KeyError):
                    # A missing guest agent or per-guest ACL must not hide the other guests
                    return None, True
            ips = sorted({ip for value in addresses if isinstance(value, str) and (ip := usable_ip(value))})
            return Guest(f"{kind}/{vmid}", name, ips), not ips

        try:
            results = await asyncio.wait_for(asyncio.gather(*(read_guest(r) for r in resources)),
                                             timeout=DISCOVERY_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise ProxmoxError("Proxmox discovery timed out. Check guest agents and network access.") from exc
        return [g for g, _ in results if g and g.addresses], sum(int(skipped) for _, skipped in results)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()


def _address_map(guests: list[Guest]) -> tuple[dict, int]:
    """IP -> {name, guest}; an address two guests report is left out instead of guessed."""
    mapping: dict[str, dict] = {}
    conflicts: set[str] = set()
    for guest in guests:
        for ip in guest.addresses:
            entry = {"name": guest.name, "guest": guest.identity}
            if ip in mapping and mapping[ip] != entry:
                conflicts.add(ip)
            mapping[ip] = entry
    for ip in conflicts:
        mapping.pop(ip)
    return mapping, len(conflicts)


def _is_automatic(name: str | None, automatic: set) -> bool:
    return not name or is_ip_like(name) or name in automatic


async def apply_guests(db, connection: ProxmoxIntegration, guests: list[Guest]) -> dict:
    """Name devices and discovered hosts by exact IP.

    Only names that were never chosen by a person are replaced: a device's display name that
    is still its IP, hostname or the previous guest name, and a discovered host without a DNS
    name. The scanner keeps owning ``hostname`` and reachability (online state, last_seen).
    """
    previous = _inventory(connection)
    mapping, conflicts = _address_map(guests)

    devices = {d.ip: d for d in (await db.execute(select(Device))).scalars()}
    discovered = {d.ip: d for d in (await db.execute(select(DiscoveredHost))).scalars()}
    renamed = 0
    for ip, entry in mapping.items():
        name = entry["name"]
        old_entry = previous.get(ip) if isinstance(previous.get(ip), dict) else {}
        old_name = old_entry.get("name") if old_entry.get("guest") == entry["guest"] else None
        device = devices.get(ip)
        if device:
            automatic = {device.ip, device.hostname, (device.hostname or "").split(".")[0], old_name} - {None, ""}
            if device.display_name != name and _is_automatic(device.display_name, automatic):
                # Explicit last_seen suppresses the onupdate timestamp: a name from Proxmox
                # is not evidence that the address answered.
                await db.execute(update(Device).where(Device.id == device.id).values(
                    display_name=name, last_seen=device.last_seen))
                renamed += 1
        host = discovered.get(ip)
        if host is None:
            db.add(DiscoveredHost(ip=ip, hostname=name, is_online=False, is_monitored=device is not None))
        elif host.hostname != name and _is_automatic(host.hostname, {old_name} - {None}):
            await db.execute(update(DiscoveredHost).where(DiscoveredHost.id == host.id).values(
                hostname=name, last_seen=host.last_seen))
        # custom_name stays the user's; a running guest is not marked reachable

    connection.inventory = json.dumps(mapping)
    connection.last_sync = datetime.now(timezone.utc).isoformat()
    connection.last_error = None
    await db.commit()
    dashboard_cache.invalidate_all()
    discovery_cache.invalidate()
    topology_cache.invalidate()
    return {"guests": len(guests), "addresses": len(mapping), "updated_devices": renamed, "conflicts": conflicts}


def _target(connection: ProxmoxIntegration) -> tuple:
    return connection.enabled, connection.url, connection.token_id, connection.encrypted_secret, connection.verify_tls


async def _reload(db) -> ProxmoxIntegration | None:
    """The connection as stored now; another request may have changed it during discovery."""
    result = await db.execute(select(ProxmoxIntegration).where(ProxmoxIntegration.id == 1)
                              .execution_options(populate_existing=True))
    return result.scalar_one_or_none()


async def sync_proxmox(db) -> dict:
    """Read all guests and apply their names. Raises ProxmoxError with a UI-safe message."""
    async with sync_lock:
        connection = await _reload(db)
        if not connection or not connection.enabled:
            raise ProxmoxError("Enable and save the Proxmox connection first.")
        target = _target(connection)
        try:
            secret = vault.decrypt(connection.encrypted_secret)
            async with ProxmoxClient(connection.url, connection.token_id, secret, connection.verify_tls) as client:
                guests, skipped = await client.discover()
        except (ProxmoxError, VaultError) as exc:
            # Never expose a response body, request headers or the token in errors and logs
            message = str(exc) if isinstance(exc, ProxmoxError) else "Cannot decrypt the Proxmox token. Check the secret vault key."
            async with write_lock:
                connection = await _reload(db)
                if connection and _target(connection) == target:
                    connection.last_error = message
                    await db.commit()
            raise ProxmoxError(message) from exc

        async with write_lock:
            connection = await _reload(db)
            if not connection or _target(connection) != target:
                raise ProxmoxError("The Proxmox settings changed during the sync. Synchronize again.")
            result = await apply_guests(db, connection, guests)
        result["skipped"] = skipped
        return result
