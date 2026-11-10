"""Network Planner Scan logic — Fast discovery via ARP/Ping/DNS."""

import logging
import ipaddress
from datetime import datetime, timezone
from docker.errors import DockerException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.database import async_session
from app.models.device import DiscoveredHost, Device
from app.models.network import Subnet
from app.scanner.discovery import discover_hosts_simple
from app.scanner.subnets import scan_target_ips
from app.scanner.arp import resolve_mac_addresses, get_local_arp_table, get_linux_stale_ips
from app.scanner.hostname import is_ip_like, resolve_hostnames
from app.scanner.presence import (
    DEFAULT_OFFLINE_THRESHOLD,
    get_offline_threshold,
    register_miss,
    register_seen,
    tcp_fallback_alive,
    update_interface_presence,
)
from app.services.cache_service import discovery_cache, dashboard_cache, topology_cache

logger = logging.getLogger(__name__)


def _normalize_subnets(subnets: list[str]) -> list[str]:
    """Ensure unique, sorted, and normalized subnet strings."""
    normalized = []
    for s in set(subnets):
        if not s:
            continue
        if "/" not in s:
            if s.count(".") == 2:
                s = f"{s}.0/24"
            elif s.count(".") == 3:
                s = f"{s}/32"
            else:
                s = f"{s}/24"
        normalized.append(s)
    return sorted(normalized)


def _parse_subnet_list(values) -> list:
    """Parse an iterable of subnet strings, skipping invalid entries."""
    nets = []
    for s in values:
        try:
            nets.append(ipaddress.ip_network(s.strip(), strict=False))
        except ValueError:
            logger.debug(f"Planner: Skipping invalid subnet '{s}'")
    return nets


async def _load_allowed_networks(db):
    """Load the enabled subnets of the Subnet table, falling back to auto-detected local subnets."""
    from app.scanner.subnets import get_scan_subnets
    return _parse_subnet_list(await get_scan_subnets(db))


def _ip_in_any_subnet(ip: str, subnets: list[str]) -> bool:
    """Return True when the IP belongs to any of the given subnets."""
    for s in subnets:
        try:
            if ipaddress.IPv4Address(ip) in ipaddress.IPv4Network(s, strict=False):
                return True
        except (ValueError, OSError):
            continue
    return False


async def _sync_local_docker_containers():
    """Best-effort sync of local Docker containers; failures must not abort the scan."""
    from app.services.docker_service import docker_service
    from app.scanner.sync import sync_docker_containers

    if not docker_service.is_available():
        return
    try:
        local_c = docker_service.get_local_containers()
        if local_c:
            logger.info(f"Planner: Syncing {len(local_c)} local Docker containers...")
            await sync_docker_containers(local_c)
    except (DockerException, SQLAlchemyError, OSError) as e:
        logger.warning(f"Planner: Docker container sync failed: {e}", exc_info=True)


async def _get_subnet_dns_servers(subnets: list[str]) -> dict[str, str]:
    """Batch-load configured DNS servers for given subnets in a single DB session."""
    if not subnets:
        return {}
    dns_map: dict[str, str] = {}
    async with async_session() as db:
        res = await db.execute(
            select(Subnet.cidr, Subnet.dns_server).where(
                Subnet.cidr.in_(subnets),
                Subnet.dns_server.isnot(None),
            )
        )
        for cidr, dns_server in res.all():
            if dns_server:
                dns_map[cidr] = dns_server
                logger.info(f"Planner: Using custom DNS {dns_server} for subnet {cidr}")
    return dns_map


async def _get_subnet_dns_server(subnet: str):
    """Return the configured DNS server for a subnet, if any."""
    servers = await _get_subnet_dns_servers([subnet])
    return servers.get(subnet)


async def _scan_subnet_alive_hosts(subnet: str, dns_server):
    """Fast ARP + Ping discovery over one subnet."""
    try:
        target_ips = scan_target_ips(subnet)
    except ValueError as e:
        logger.error(f"Planner: Skipping invalid subnet '{subnet}': {e}")
        return []

    # No more immediate per-host callback to DB to prevent locks
    return await discover_hosts_simple(target_ips, dns_server=dns_server)


async def _cleanup_discovered_hosts(db, subnets: list[str], all_alive_ips: set):
    """Delete unmonitored discovered hosts absent from the scan; mark monitored ones offline."""
    res_disc = await db.execute(select(DiscoveredHost).where(DiscoveredHost.is_online == True))
    for host in res_disc.scalars().all():
        if not _ip_in_any_subnet(host.ip, subnets) or host.ip in all_alive_ips:
            continue

        # IMPORTANT: Only delete if NOT monitored.
        # Dashboard devices are handled by dashboard scanner.
        if not host.is_monitored:
            logger.info(f"Planner: Host {host.ip} GONE, deleting.")
            await db.delete(host)
        else:
            # Just mark as offline for UI consistency until Dashboard scan confirms
            host.is_online = False


async def _cleanup_devices(
    db, subnets: list[str], all_alive_ips: set, offline_threshold: int = DEFAULT_OFFLINE_THRESHOLD
):
    """Count a miss for devices absent from the scan; they go offline only at the threshold."""
    res_dev = await db.execute(select(Device).where(Device.is_online == True))
    missing = []
    for dev in res_dev.scalars().all():
        if not _ip_in_any_subnet(dev.ip, subnets):
            continue
        if dev.ip in all_alive_ips:
            register_seen(dev)
            continue

        # Skipping: Devices with configured services are handled by the
        # Dashboard scanner (TCP port + ICMP hybrid check). Marking them
        # offline here based on a single missed ping causes false positives
        # on devices with a busy management CPU (e.g. UniFi switches).
        if dev.services:
            continue
        missing.append(dev)

    # ICMP/ARP silence alone is no proof of absence (e.g. ipvlan containers
    # on Unraid), so try a TCP handshake before counting the miss.
    tcp_alive = await tcp_fallback_alive([dev.ip for dev in missing])
    for dev in missing:
        if dev.ip in tcp_alive:
            register_seen(dev)
        else:
            await register_miss(dev, db, offline_threshold)


async def _cleanup_planner_offline(
    db, subnets: list[str], all_alive_ips: set, offline_threshold: int = DEFAULT_OFFLINE_THRESHOLD
):
    """
    Delete unmonitored discovered hosts and count misses for devices that
    were absent from the planner scan (exclusive to the planner scanner).
    """
    await _cleanup_discovered_hosts(db, subnets, all_alive_ips)
    await _cleanup_devices(db, subnets, all_alive_ips, offline_threshold)
    await update_interface_presence(db, subnets, all_alive_ips, offline_threshold)


async def run_arp_only_scan():
    """
    Extremely fast scan that only looks at the local ARP table.
    Used for the Turbo mode. Filters results by the enabled scan subnets.
    """
    async with async_session() as db:
        allowed_nets = await _load_allowed_networks(db)

    arp_hosts = get_local_arp_table()
    for stale_ip in get_linux_stale_ips():
        arp_hosts.pop(stale_ip, None)
    hosts_to_sync = []

    for ip, mac in arp_hosts.items():
        if not mac or mac == "00:00:00:00:00:00":
            continue

        try:
            ip_obj = ipaddress.IPv4Address(ip)
            if any(ip_obj in net for net in allowed_nets):
                hosts_to_sync.append({"ip": ip, "mac": mac})
        except (ValueError, OSError):
            logger.debug(f"Planner: Skipping invalid ARP entry {ip}")

    if hosts_to_sync:
        from app.scanner.sync import sync_hosts_batch
        await sync_hosts_batch(hosts_to_sync, is_planner_scan=True)

    return len(hosts_to_sync)


def _skip_reason(subnet: str) -> str:
    """Why the scan leaves a subnet out (the validation message, e.g. 'too large to scan')."""
    try:
        scan_target_ips(subnet)
    except ValueError as e:
        return str(e)
    return "no addresses to scan"


def _target_count(subnet: str) -> int:
    """Host addresses the scan sweeps in a subnet, 0 for one it skips (invalid or too large, #43)."""
    try:
        return len(scan_target_ips(subnet))
    except ValueError:
        return 0


async def _scan_and_resolve_subnet(
    subnet: str, dns_server: str | None, progress_callback=None
) -> list[dict]:
    """Fast discovery (ARP+Ping), MAC resolution, and DNS hostname resolution for one subnet."""
    if progress_callback:
        await progress_callback(f"Scanner: Scanning {subnet} (ARP + Ping)...")

    # 1. Fast Discovery (Nmap -sn -PR -PE)
    alive_hosts = await _scan_subnet_alive_hosts(subnet, dns_server)

    if progress_callback:
        await progress_callback(f"Scanner: Found {len(alive_hosts)} active hosts. Resolving MACs...")

    # 2. MAC Resolution & Batch Sync (scoped to this subnet's target IPs)
    try:
        subnet_target_ips = scan_target_ips(subnet)
    except ValueError:
        subnet_target_ips = None
    resolved_hosts = await resolve_mac_addresses(alive_hosts, all_target_ips=subnet_target_ips)

    # 2b. Names nmap's reverse DNS missed: NetBIOS, mDNS, OS resolver, ping -a
    nameless = [h for h in resolved_hosts if is_ip_like(h.get("hostname"))]
    if nameless:
        if progress_callback:
            await progress_callback(f"Scanner: Resolving names of {len(nameless)} hosts...")
        await resolve_hostnames(nameless, dns_server=dns_server, max_concurrent=10)

    return resolved_hosts


async def _post_scan_cleanup(subnets: list[str], all_alive_ips: set) -> None:
    """Offline cleanup, mark initial scan done, and invalidate caches."""
    async with async_session() as db:
        offline_threshold = await get_offline_threshold(db)
        await _cleanup_planner_offline(db, subnets, all_alive_ips, offline_threshold)
        from app.models.setting import Setting
        res_done = await db.execute(select(Setting).where(Setting.key == "scanner.initial_scan_done"))
        if res_done.scalar_one_or_none() is None:
            db.add(Setting(key="scanner.initial_scan_done", value="true", category="scan"))
        await db.commit()
        # Consolidated cache invalidation
        discovery_cache.invalidate()
        dashboard_cache.invalidate_all()
        topology_cache.invalidate()


async def _announce_scan_complete(total_found: int) -> None:
    """Send scan.complete webhook event."""
    from app.services.webhook_service import trigger_webhooks
    await trigger_webhooks(
        event_type="scan.complete",
        data={
            "scan_type": "planner",
            "hosts_found": total_found,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )


async def run_planner_scan(subnets: list[str], progress_callback=None, hosts_callback=None, announce: bool = True):
    """
    Executes a lightweight discovery scan for the Network Planner.
    Uses ARP + Ping + DNS.

    ``hosts_callback(subnet, hosts_scanned, hosts_total)`` is awaited when a subnet starts and
    when it is done; nmap sweeps a whole subnet at once, so the count moves per subnet.
    ``announce=False`` for the recurring quick checks: every few minutes is no news worth a scan.complete.
    """
    subnets = _normalize_subnets(subnets)
    logger.info(f"Planner: Starting discovery on {subnets}")

    # Sync local Docker containers first
    await _sync_local_docker_containers()

    total_found = 0
    all_alive_ips = set()
    from app.scanner.sync import sync_hosts_batch

    valid_subnets = [s for s in subnets if not s.startswith("169.254.")]
    targets = {s: _target_count(s) for s in valid_subnets}
    # A subnet the scan cannot sweep (larger than a /16, or not IPv4) is said so in the scan's own
    # progress, not just the server log, and stays out of the offline cleanup: nothing in it was looked at
    skipped = [s for s in valid_subnets if targets[s] == 0]
    for subnet in skipped:
        reason = _skip_reason(subnet)
        logger.warning("Planner: Skipping subnet %s: %s", subnet, reason)
        if progress_callback:
            await progress_callback(f"Scanner: Skipping {subnet}: {reason}")
    subnets = [s for s in subnets if s not in skipped]
    valid_subnets = [s for s in valid_subnets if s not in skipped]
    hosts_total = sum(targets.values())
    hosts_scanned = 0

    dns_servers = await _get_subnet_dns_servers(valid_subnets)

    for subnet in subnets:
        if subnet.startswith("169.254."):
            continue

        if hosts_callback:
            await hosts_callback(subnet, hosts_scanned, hosts_total)

        dns_server = dns_servers.get(subnet)
        resolved_hosts = await _scan_and_resolve_subnet(subnet, dns_server, progress_callback)

        if resolved_hosts:
            await sync_hosts_batch(resolved_hosts, is_planner_scan=True)
            for h in resolved_hosts:
                all_alive_ips.add(h["ip"])
                total_found += 1

            if progress_callback:
                await progress_callback("EVENT:RELOAD_DEVICES")

        hosts_scanned += targets.get(subnet, 0)
        if hosts_callback:
            await hosts_callback(subnet, hosts_scanned, hosts_total)

    # Offline Cleanup & Cache Invalidation (Exclusive to Planner)
    await _post_scan_cleanup(subnets, all_alive_ips)

    logger.info(f"Planner: Scan complete. Found {total_found} hosts.")

    if announce:
        await _announce_scan_complete(total_found)

    return total_found
