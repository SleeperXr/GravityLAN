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
from fastapi import HTTPException
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

# What the last sync found, for Settings > Proxmox VE > Last sync. Kept in memory only:
# the next sync (at most five minutes away) rebuilds it, so no table or migration is needed.
last_report: dict | None = None


def clear_report() -> None:
    global last_report
    last_report = None


class ProxmoxError(Exception):
    """A safe, credential-free error suitable for the settings UI."""


@dataclass
class Guest:
    identity: str  # "qemu/100" or "lxc/101"
    name: str
    addresses: list[str]


@dataclass
class Skipped:
    identity: str
    name: str
    # vm_stopped: a stopped VM has no guest agent to ask
    # unreadable: the agent or interface list could not be read (no agent, no permission)
    # no_address: read fine, but no usable address (e.g. a stopped container with DHCP)
    # incomplete: Proxmox listed the guest without a name, node or ID
    reason: str


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

    async def discover(self) -> tuple[list[Guest], list[Skipped]]:
        """All VMs and containers with at least one usable address, and the ones skipped with the reason."""
        resources = await self.get("cluster/resources?type=vm")
        if not isinstance(resources, list):
            raise ProxmoxError("Proxmox returned an invalid guest list.")
        semaphore = asyncio.Semaphore(4)

        async def read_guest(resource) -> Guest | Skipped | None:
            if not isinstance(resource, dict) or resource.get("type") not in ("qemu", "lxc") or resource.get("template"):
                return None
            kind = resource["type"]
            vmid = resource.get("vmid")
            node = resource.get("node")
            name = str(resource.get("name") or "").strip()[:100]
            identity = f"{kind}/{vmid}"
            if not name or not node or not isinstance(vmid, int):
                return Skipped(identity, name, "incomplete")
            running = resource.get("status") == "running"
            # A stopped VM has no guest agent to ask; never reuse stale agent data.
            if kind == "qemu" and not running:
                return Skipped(identity, name, "vm_stopped")
            prefix = f"nodes/{quote(str(node), safe='')}/{kind}/{vmid}"
            async with semaphore:
                try:
                    addresses = await self._guest_addresses(prefix, kind, running)
                except (ProxmoxError, TypeError, AttributeError, KeyError):
                    # A missing guest agent or per-guest ACL must not hide the other guests
                    return Skipped(identity, name, "unreadable")
            ips = sorted({ip for value in addresses if isinstance(value, str) and (ip := usable_ip(value))})
            return Guest(identity, name, ips) if ips else Skipped(identity, name, "no_address")

        try:
            results = await asyncio.wait_for(asyncio.gather(*(read_guest(r) for r in resources)),
                                             timeout=DISCOVERY_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise ProxmoxError("Proxmox discovery timed out. Check guest agents and network access.") from exc
        return [r for r in results if isinstance(r, Guest)], [r for r in results if isinstance(r, Skipped)]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()


def _networks(subnets: list[str] | None):
    if subnets is None:
        return None
    nets = []
    for cidr in subnets:
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    return nets


def _in_networks(ip: str, nets) -> bool:
    addr = ipaddress.ip_address(ip)
    return any(addr.version == net.version and addr in net for net in nets)


def _is_automatic(name: str | None, automatic: set) -> bool:
    return not name or is_ip_like(name) or name in automatic


async def apply_guests(db, connection: ProxmoxIntegration, guests: list[Guest],
                       subnets: list[str] | None = None, skipped: list[Skipped] | None = None) -> dict:
    """Name devices and discovered hosts by exact IP and describe what happened.

    Only addresses in the scan subnets (or of an existing device) are used; container
    bridges such as 172.17.0.1 or IPv6 addresses outside them are only listed. An address
    two guests report is left out instead of guessed. Only names never chosen by a person
    are replaced: a display name that is still the IP, hostname or previous guest name, and
    the hostname of a discovered host without a DNS name. The scanner keeps owning
    ``hostname`` and reachability (online state, last_seen).
    """
    previous = _inventory(connection)
    nets = _networks(subnets)
    devices = {d.ip: d for d in (await db.execute(select(Device))).scalars()}
    discovered = {d.ip: d for d in (await db.execute(select(DiscoveredHost))).scalars()}

    statuses: dict[tuple[str, str], str] = {}  # (guest, ip) -> status for the report
    owners: dict[str, list[Guest]] = {}
    for guest in guests:
        for ip in guest.addresses:
            if nets is not None and ip not in devices and not _in_networks(ip, nets):
                statuses[(guest.identity, ip)] = "outside"
            else:
                owners.setdefault(ip, []).append(guest)

    conflicts = []
    mapping: dict[str, dict] = {}
    for ip, owned_by in owners.items():
        if len({g.identity for g in owned_by}) > 1:
            conflicts.append({"ip": ip, "guests": sorted({g.name for g in owned_by})})
            for g in owned_by:
                statuses[(g.identity, ip)] = "conflict"
        else:
            mapping[ip] = {"name": owned_by[0].name, "guest": owned_by[0].identity}

    renamed = 0
    for ip, entry in mapping.items():
        name = entry["name"]
        old_entry = previous.get(ip) if isinstance(previous.get(ip), dict) else {}
        old_name = old_entry.get("name") if old_entry.get("guest") == entry["guest"] else None
        device = devices.get(ip)
        status = "host"
        if device:
            status = "device"
            automatic = {device.ip, device.hostname, (device.hostname or "").split(".")[0], old_name} - {None, ""}
            if device.display_name != name and _is_automatic(device.display_name, automatic):
                # Explicit last_seen suppresses the onupdate timestamp: a name from Proxmox
                # is not evidence that the address answered.
                await db.execute(update(Device).where(Device.id == device.id).values(
                    display_name=name, last_seen=device.last_seen))
                renamed += 1
                status = "renamed"
        host = discovered.get(ip)
        if host is None:
            db.add(DiscoveredHost(ip=ip, hostname=name, is_online=False, is_monitored=device is not None))
            status = "new_host" if not device else status
        elif host.hostname != name and _is_automatic(host.hostname, {old_name} - {None}):
            await db.execute(update(DiscoveredHost).where(DiscoveredHost.id == host.id).values(
                hostname=name, last_seen=host.last_seen))
        # custom_name stays the user's; a running guest is not marked reachable
        statuses[(entry["guest"], ip)] = status

    now = datetime.now(timezone.utc).isoformat()
    connection.inventory = json.dumps(mapping)
    connection.last_sync = now
    connection.last_error = None
    await db.commit()
    dashboard_cache.invalidate_all()
    discovery_cache.invalidate()
    topology_cache.invalidate()

    global last_report
    last_report = {
        "synced_at": now,
        "subnets": subnets,
        "guests": [{"guest": g.identity, "name": g.name,
                    "addresses": [{"ip": ip, "status": statuses.get((g.identity, ip), "host")} for ip in g.addresses]}
                   for g in sorted(guests, key=lambda g: g.name.lower())],
        "skipped": [{"guest": s.identity, "name": s.name, "reason": s.reason} for s in (skipped or [])],
        "conflicts": sorted(conflicts, key=lambda c: c["ip"]),
    }
    outside = sum(1 for s in statuses.values() if s == "outside")
    return {"guests": len(guests), "addresses": len(mapping), "updated_devices": renamed,
            "conflicts": len(conflicts), "outside": outside}


MAX_ADD_AT_ONCE = 256


async def add_guests_to_dashboard(db, ips: list[str]) -> list[dict]:
    """Put guests of the last sync on the dashboard, named after the guest. Only on request:
    a sync itself never creates a device.

    Only addresses of the last sync are accepted, so this cannot add arbitrary hosts. The
    device is created the usual way (MAC and vendor lookup); a display name that is still
    automatic becomes the guest name right away instead of with the next sync.
    """
    from app.api.devices import add_device_from_ip

    async with write_lock:
        connection = await db.get(ProxmoxIntegration, 1)
        if not connection or not connection.enabled:
            raise ProxmoxError("Enable and save the Proxmox connection first.")
        inventory = _inventory(connection)
        wanted = list(dict.fromkeys(ips))
        unknown = [ip for ip in wanted if ip not in inventory]
        if unknown:
            raise ProxmoxError(f"Not an address of the last Proxmox sync: {', '.join(unknown[:5])}")

        added = []
        for ip in wanted:
            name = inventory[ip].get("name") or ip
            try:
                device = await add_device_from_ip(ip, db)
            except HTTPException:
                continue  # e.g. an IPv6 address: the dashboard takes IPv4 devices only
            automatic = {device.ip, device.hostname, (device.hostname or "").split(".")[0]} - {None, ""}
            if device.display_name != name and _is_automatic(device.display_name, automatic):
                device.display_name = name
            await db.execute(update(DiscoveredHost).where(DiscoveredHost.ip == ip).values(
                is_monitored=True, last_seen=DiscoveredHost.last_seen))
            await db.commit()
            added.append({"ip": ip, "id": device.id, "name": device.display_name})

    dashboard_cache.invalidate_all()
    discovery_cache.invalidate()
    topology_cache.invalidate()
    if last_report:
        done = {a["ip"] for a in added}
        for guest in last_report["guests"]:
            for address in guest["addresses"]:
                if address["ip"] in done:
                    address["status"] = "device"
    return added


def _target(connection: ProxmoxIntegration) -> tuple:
    return connection.enabled, connection.url, connection.token_id, connection.encrypted_secret, connection.verify_tls


async def _reload(db) -> ProxmoxIntegration | None:
    """The connection as stored now; another request may have changed it during discovery."""
    result = await db.execute(select(ProxmoxIntegration).where(ProxmoxIntegration.id == 1)
                              .execution_options(populate_existing=True))
    return result.scalar_one_or_none()


async def _scan_subnets(db) -> list[str]:
    """The networks GravityLAN scans: the enabled subnets, else the auto-detected local ones."""
    from app.scanner.subnets import get_enabled_subnets
    from app.scanner.utils import get_auto_scan_subnets
    return await get_enabled_subnets(db) or get_auto_scan_subnets()


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

        subnets = await _scan_subnets(db)
        async with write_lock:
            connection = await _reload(db)
            if not connection or _target(connection) != target:
                raise ProxmoxError("The Proxmox settings changed during the sync. Synchronize again.")
            result = await apply_guests(db, connection, guests, subnets, skipped)
        result["skipped"] = len(skipped)
        return result
