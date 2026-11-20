"""Shared synchronization logic for both Planner and Dashboard scans."""

import asyncio
import ipaddress
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm.exc import StaleDataError

from app.database import async_session
from app.models.device import Device, DeviceHistory, DeviceInterface, DiscoveredHost
from app.models.network import Subnet
from app.scanner.gateways import detect_default_gateways, effective_gateway
from app.scanner.vendor import get_vendor
from app.scanner.hostname import is_ip_like
from app.services.cache_service import discovery_cache, dashboard_cache, topology_cache
from app.services.mac_observations import (
    ReportedPairs,
    clear_observations,
    clear_open_observations,
    collect_usable_macs_by_ip,
    macs_differ,
    open_conflict_device_ids,
    record_mac_conflict,
)

logger = logging.getLogger(__name__)


@dataclass
class SyncContext:
    """The configured subnets and their gateways, loaded once per batch instead of per host."""

    networks: list = field(default_factory=list)  # [(ip_network, Subnet)], most specific first
    gateways: dict = field(default_factory=dict)  # Subnet.id -> effective gateway ip
    gateway_sources: dict = field(default_factory=dict)  # Subnet.id -> configured/detected/suggested
    is_initial: bool = True
    # Sent once the batch is committed: a rollback must not announce what the next scan finds again
    pending_webhooks: list = field(default_factory=list)  # [(event_type, data)]
    # (device id, MAC) conflicts already noted in this batch (app.services.mac_observations)
    reported_macs: ReportedPairs = field(default_factory=ReportedPairs)
    # All usable normalised MACs seen per IP in this batch (detects ambiguous A+B passes)
    batch_macs_by_ip: dict[str, set[str]] = field(default_factory=dict)

    def subnet_for(self, ip: str | None):
        try:
            addr = ipaddress.ip_address(ip)
        except (ValueError, TypeError):
            return None
        return next((sub for net, sub in self.networks if addr in net), None)

    def segment(self, ip: str | None) -> str | None:
        """The configured subnet holding `ip`, else the /24 around it (None for non-IPs)."""
        sub = self.subnet_for(ip)
        if sub:
            return sub.cidr
        try:
            return str(ipaddress.ip_network(f"{ip}/24", strict=False))
        except (ValueError, TypeError):
            return None

    def is_cross_segment(self, a: str | None, b: str | None) -> bool:
        seg_a, seg_b = self.segment(a), self.segment(b)
        return bool(seg_a and seg_b and seg_a != seg_b)

    def is_gateway(self, ip: str | None) -> bool:
        return self.gateway_source(ip) is not None

    def gateway_source(self, ip: str | None) -> str | None:
        """How `ip` is known as its subnet's gateway (configured/detected/suggested), or None."""
        sub = self.subnet_for(ip)
        if not sub or self.gateways.get(sub.id) != ip:
            return None
        return self.gateway_sources.get(sub.id)


async def load_sync_context(db) -> SyncContext:
    subnets = (await db.execute(select(Subnet))).scalars().all()
    detected = detect_default_gateways()
    ctx = SyncContext()
    for sub in subnets:
        try:
            ctx.networks.append((ipaddress.ip_network(sub.cidr, strict=False), sub))
        except (ValueError, TypeError):
            continue
        gw = effective_gateway(sub, detected)
        if gw:
            ctx.gateways[sub.id] = gw.ip
            ctx.gateway_sources[sub.id] = gw.source
    ctx.networks.sort(key=lambda pair: pair[0].prefixlen, reverse=True)
    ctx.is_initial = await is_initial_inventory(db)
    return ctx

_INVALID_MACS = ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff")
_MULTICAST_MAC_PREFIXES = ("01:00:5e", "33:33")


def _mac_is_valid(mac: str | None) -> bool:
    return bool(
        mac and mac.strip()
        and mac.lower() not in _INVALID_MACS
        and not mac.lower().startswith(_MULTICAST_MAC_PREFIXES)
    )


@dataclass(frozen=True)
class ScanHit:
    """What one scan learned about one host."""

    ip: str | None
    mac: str | None
    hostname: str | None = None
    vendor: str | None = None
    ports: list[int] | None = None

    @classmethod
    def from_host(cls, host: dict) -> "ScanHit":
        return cls(host.get("ip"), host.get("mac"), host.get("hostname"), host.get("vendor"), host.get("ports"))

    @property
    def is_valid_mac(self) -> bool:
        return _mac_is_valid(self.mac)


def _mark_seen(record) -> None:
    """A Device or DiscoveredHost answered just now: online, and no longer a placeholder."""
    record.is_online = True
    record.last_seen = datetime.now(timezone.utc)
    if getattr(record, "ip_placeholder", False):
        record.ip_placeholder = False


def _should_apply_custom_name(disc, dev) -> bool:
    """True when a scan-provided custom name may overwrite the device display name."""
    if not disc:
        return False
    if not disc.custom_name:
        return False
    return not dev.display_name or dev.display_name == "Unknown"


async def is_initial_inventory(db) -> bool:
    """True when GravityLAN is performing its initial inventory pass.

    During initial inventory (before scanner.initial_scan_done is recorded),
    no new_device alerts are fired.
    """
    from app.models.setting import Setting
    res_done = await db.execute(select(Setting.value).where(Setting.key == "scanner.initial_scan_done"))
    return res_done.scalar_one_or_none() != "true"


async def sync_host_to_db(ip: str, mac: str | None, hostname: str | None = None, vendor: str | None = None, ports: list[int] | None = None, is_planner_scan: bool = True, should_invalidate_cache: bool = True):
    """
    Wrapper for sync_hosts_batch for single host updates.
    """
    host_data = {
        "ip": ip,
        "mac": mac,
        "hostname": hostname,
        "vendor": vendor,
        "ports": ports
    }
    return await sync_hosts_batch([host_data], is_planner_scan, should_invalidate_cache)


BATCH_ATTEMPTS = 5


def _is_lock_error(e: OperationalError) -> bool:
    error_msg = str(e).lower()
    return "locked" in error_msg or "busy" in error_msg


async def commit_or_discard(db) -> str:
    """Commit once; returns 'ok', 'stale' or 'locked'.

    A failed commit is rolled back, and the rollback discards every change the session held:
    committing again afterwards would commit nothing. Whoever gets 'locked' has to redo the
    work in a new session, or give it up. Other database errors are raised.
    """
    try:
        await db.commit()
        return "ok"
    except StaleDataError:
        await db.rollback()
        logger.debug("Sync: Stale data encountered during batch commit, rolling back.")
        return "stale"
    except OperationalError as e:
        await db.rollback()
        if _is_lock_error(e):
            return "locked"
        logger.error(f"Sync: Batch DB failure: {e}")
        raise


async def _sync_batch_once(hosts: list[dict]) -> tuple[str, list, "SyncContext"]:
    """Apply ``hosts`` in one new session and commit; returns (commit outcome, results, context)."""
    results = []
    async with async_session() as db:
        ctx = await load_sync_context(db)
        ctx.batch_macs_by_ip = collect_usable_macs_by_ip(hosts)
        for position, host in enumerate(hosts, start=1):
            try:
                res = await _sync_host_internal(db, host, ctx)
                results.append(res)
            except OperationalError as e:
                # A lock met by a flush or DELETE inside one host leaves the session unusable:
                # the whole batch is redone, not just this host skipped
                if not _is_lock_error(e):
                    raise
                await db.rollback()
                return "locked", [], ctx
            except Exception:
                # Nothing of the host itself (address, MAC, names) and nothing of the error built
                # from it goes into the log, only where in the batch it was
                logger.error("Sync: Failed to process host %d of %d in the batch; it was skipped", position, len(hosts))

        outcome = await commit_or_discard(db)
    return outcome, results, ctx


async def _sync_batch_with_retry(hosts: list[dict]) -> tuple[bool, list, "SyncContext"]:
    """Redo the whole batch while the database is locked; raises once the attempts run out."""
    for attempt in range(BATCH_ATTEMPTS):
        try:
            outcome, results, ctx = await _sync_batch_once(hosts)
        except OperationalError as e:
            # The reads that load the context can meet a busy database too; the session of
            # this attempt is closed by then, the next one starts fresh
            if not _is_lock_error(e):
                raise
            outcome = "locked"
        if outcome != "locked":
            return outcome == "ok", results, ctx
        if attempt < BATCH_ATTEMPTS - 1:
            await asyncio.sleep((attempt + 1) * 0.2)
    logger.error("Sync: database still locked after %d attempts, %d host(s) not saved", BATCH_ATTEMPTS, len(hosts))
    raise OperationalError("sync_hosts_batch", None, Exception("database is locked"))


async def sync_hosts_batch(hosts: list[dict], is_planner_scan: bool = True, should_invalidate_cache: bool = True):
    """
    Synchronizes multiple hosts in a single database transaction.
    Significantly reduces I/O pressure and prevents 'Database is locked' errors.
    """
    if not hosts:
        return []

    committed, results, ctx = await _sync_batch_with_retry(hosts)
    if not committed:
        # Stale data rolled the batch back: its records were not saved (and are expired), so none are returned
        return []

    if ctx.pending_webhooks:
        from app.services.webhook_service import trigger_webhooks
        for event_type, data in ctx.pending_webhooks:
            await trigger_webhooks(event_type=event_type, data=data)

    if should_invalidate_cache:
        discovery_cache.invalidate()
        # Only invalidate dashboard/topology if a device was actually updated/matched
        # For performance, we could be more selective, but this is safer for now.
        dashboard_cache.invalidate_all()
        topology_cache.invalidate()

    return results


def _mac_equals(model, mac: str):
    """Case-insensitive MAC comparison: older rows from the agent relay are upper case."""
    return func.lower(model.mac) == (mac or "").lower()


async def _query_by_mac_and_ip(db, model, mac: str, ip: str):
    res = await db.execute(select(model).where(_mac_equals(model, mac), model.ip == ip))
    return res.scalar_one_or_none()


async def _query_by_ip(db, model, ip: str):
    res = await db.execute(select(model).where(model.ip == ip))
    return res.scalar_one_or_none()


async def _query_by_mac_all(db, model, mac: str):
    res = await db.execute(select(model).where(_mac_equals(model, mac)))
    return res.scalars().all()


async def _query_by_mac_ordered(db, model, mac: str):
    res = await db.execute(
        select(model)
        .where(_mac_equals(model, mac))
        .order_by(model.is_monitored.desc(), model.custom_name.desc())
    )
    return res.scalars().all()


async def _query_by_name(db, model, name: str, name_columns):
    # Literal, case-insensitive: with ilike a "_" or "%" in a name was a wildcard ("esp_01" found "esp-01")
    clauses = [func.lower(col) == name.lower() for col in name_columns]
    res = await db.execute(select(model).where(or_(*clauses)))
    return res.scalars().all()


def _is_unraid_host(entity) -> bool:
    """True when any of the record's names or its vendor mentions Unraid (case-insensitive)."""
    for attr in ("display_name", "custom_name", "hostname", "vendor"):
        value = getattr(entity, attr, None)
        if value and "unraid" in value.lower():
            return True
    return False


def _macs_conflict(known_mac: str | None, mac: str, is_valid_mac: bool) -> bool:
    return bool(is_valid_mac and _mac_is_valid(known_mac) and known_mac.lower() != mac.lower())


async def _mac_owner_allows_ip_match(db, model, mac: str, cand) -> bool:
    """True when the record that holds the scanned MAC does not rule out the IP match on `cand`."""
    mac_owners = [owner for owner in await _query_by_mac_all(db, model, mac) if owner.id != cand.id]
    if len(mac_owners) != 1:
        # No owner: nothing speaks against the IP. Several records behind one MAC is the
        # ipvlan pattern (containers share the host's MAC): the MAC can't tell them apart,
        # so the IP match stands. Asking for a single owner here raised
        # MultipleResultsFound and skipped the host every scan.
        return True
    return _is_unraid_host(mac_owners[0])


async def _match_ip_with_mac_conflict(db, model, mac: str, ip: str, is_valid_mac: bool):
    """
    IP-only match that prefers a candidate whose MAC conflicts with the scanned MAC
    only if the MAC owner is an Unraid host (otherwise the candidate is rejected).
    """
    cand = await _query_by_ip(db, model, ip)
    if not cand or not _macs_conflict(cand.mac, mac, is_valid_mac):
        return cand
    return cand if await _mac_owner_allows_ip_match(db, model, mac, cand) else None


async def _match_by_address(db, model, hit: ScanHit):
    """The record at the scanned address. Returns (record, "exact" or "ip") or (None, None)."""
    if not hit.ip:
        return None, None
    if hit.is_valid_mac:
        exact = await _query_by_mac_and_ip(db, model, hit.mac, hit.ip)
        if exact:
            return exact, "exact"
    cand = await _match_ip_with_mac_conflict(db, model, hit.mac, hit.ip, hit.is_valid_mac)
    return (cand, "ip") if cand else (None, None)


async def _match_by_name(db, model, hit: ScanHit, name_columns):
    """The record with the scanned name, unless its MAC says it is another box.

    A name is the weakest clue: a second device with the same name (a replacement, a default
    hostname, a user-given name that is another box's hostname) would otherwise take over the
    record, its notes, links and probes. A different valid MAC makes the hit a new candidate;
    without a MAC on either side the name still follows a DHCP move.
    """
    name = hit.hostname
    if not name or is_ip_like(name):
        return None
    candidates = [
        c for c in await _query_by_name(db, model, name, name_columns)
        if not _macs_conflict(c.mac, hit.mac, hit.is_valid_mac)
    ]
    if not candidates:
        return None
    placeholder = next((c for c in candidates if getattr(c, "ip_placeholder", False)), None)
    return placeholder or candidates[0]


async def _match_dashboard_device(db, hit: ScanHit):
    """Match a monitored Device. Returns (device, match_type) or (None, None)."""
    dev, match_type = await _match_by_address(db, Device, hit)
    if dev:
        return dev, match_type

    dev = await _match_dashboard_by_mac(db, hit.mac, hit.ip, hit.is_valid_mac)
    if dev:
        return dev, "mac"

    dev = await _match_by_name(db, Device, hit, (Device.hostname, Device.display_name))
    return (dev, "hostname") if dev else (None, None)


async def _match_dashboard_by_mac(db, mac: str, ip: str, is_valid_mac: bool):
    """MAC-only fallback for monitored Devices; guards against Unraid IP hijacking."""
    if not is_valid_mac:
        return None
    matches = await _query_by_mac_all(db, Device, mac)
    if len(matches) == 1:
        cand = matches[0]
        if cand.ip != ip and _is_unraid_host(cand):
            logger.debug(f"Sync: Skipping MAC match for host {cand.display_name} ({cand.ip}) on new IP {ip} to prevent host IP hijacking.")
            return None
        return cand
    if len(matches) > 1:
        logger.debug(f"Sync: Multiple devices found for MAC {mac} (ipvlan). Skipping MAC-only fallback matching.")
    return None


async def _match_discovered_host(db, hit: ScanHit, ctx: SyncContext | None = None):
    """Match a DiscoveredHost record. Returns the record or None."""
    disc, _ = await _match_by_address(db, DiscoveredHost, hit)
    if disc:
        return disc

    disc = _unless_live_elsewhere(await _match_discovered_by_mac(db, hit.mac, hit.is_valid_mac), hit.ip, ctx)
    if disc:
        return disc
    by_name = await _match_by_name(db, DiscoveredHost, hit, (DiscoveredHost.hostname, DiscoveredHost.custom_name))
    disc = _unless_live_elsewhere(by_name, hit.ip, ctx)
    if disc:
        return disc
    # Every fallback was turned down, e.g. the MAC owner is still online in another VLAN.
    # An address holds one record: a new row here would break the unique IP and lose the
    # whole scan batch, so the record at this address stands, as for any other IP match.
    return await _query_by_ip(db, DiscoveredHost, hit.ip)


def _unless_live_elsewhere(record, ip: str, ctx: SyncContext | None):
    return None if record is None or _is_live_record_elsewhere(record, ip, ctx) else record


def _is_live_record_elsewhere(record, ip: str, ctx: SyncContext | None) -> bool:
    """A fallback hit that is still online in another subnet is the same box on a second address.

    A router answers with one MAC (and often one name) in every VLAN; moving its record
    to the new address would make it jump between its VLAN addresses on every scan.
    """
    if ctx is None or record.ip == ip or not record.is_online:
        return False
    return ctx.is_cross_segment(record.ip, ip)


async def _match_discovered_by_mac(db, mac: str, is_valid_mac: bool):
    """MAC-only fallback for DiscoveredHost records."""
    if not is_valid_mac:
        return None
    matches = await _query_by_mac_ordered(db, DiscoveredHost, mac)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        logger.debug(f"Sync: Multiple DiscoveredHost records found for MAC {mac} (ipvlan). Skipping MAC-only matching.")
    return None


async def _upsert_discovered_host(db, disc, dev, hit: ScanHit):
    """Update an existing DiscoveredHost or create a new one. Does NOT commit."""
    if disc:
        return await _update_existing_discovered_host(db, disc, dev, hit)

    inherited_name = dev.display_name if (dev and dev.ip == hit.ip) else None

    disc = DiscoveredHost(
        ip=hit.ip, mac=hit.mac, hostname=hit.hostname,
        custom_name=inherited_name,
        vendor=hit.vendor or (await asyncio.to_thread(get_vendor, hit.mac) if hit.mac else None),
        is_online=True,
        is_monitored=dev is not None,
        last_seen=datetime.now(timezone.utc),
        first_seen=datetime.now(timezone.utc),
        ports=json.dumps(hit.ports) if hit.ports else None
    )
    db.add(disc)
    return disc


async def _move_discovered_host(db, disc, ip: str) -> None:
    """Give `disc` the address `ip`, removing any other record that holds it. Does NOT commit."""
    if disc.ip == ip:
        return
    await db.execute(delete(DiscoveredHost).where(DiscoveredHost.ip == ip).where(DiscoveredHost.id != disc.id))
    disc.ip = ip


def _apply_scan_fields(disc, hit: ScanHit) -> None:
    """Copy what the scan found onto `disc`; an empty scan field keeps the known value."""
    if hit.hostname:
        disc.hostname = hit.hostname
    if hit.is_valid_mac and not _mac_is_valid(disc.mac):
        disc.mac = hit.mac
    if hit.vendor:
        disc.vendor = hit.vendor
    if hit.ports:
        disc.ports = json.dumps(hit.ports)


async def _update_existing_discovered_host(db, disc, dev, hit: ScanHit):
    """Apply scan results to an existing DiscoveredHost. Does NOT commit."""
    await _move_discovered_host(db, disc, hit.ip)
    _mark_seen(disc)
    _apply_scan_fields(disc, hit)

    if not disc.custom_name and dev and dev.ip == hit.ip:
        disc.custom_name = dev.display_name

    disc.is_monitored = dev is not None
    return disc


def _is_reusable_old_ip(old_ip: str | None) -> bool:
    if not old_ip:
        return False
    if old_ip.startswith("offline-"):
        return False
    return is_ip_like(old_ip)


async def _find_safe_placeholder_ip(db, conflict_dev):
    old_ip = getattr(conflict_dev, "old_ip", None)
    if _is_reusable_old_ip(old_ip):
        res_taken = await db.execute(select(Device).where(Device.ip == old_ip).where(Device.id != conflict_dev.id))
        if not res_taken.scalar_one_or_none():
            return old_ip

    counter = 0
    while True:
        candidate = f"0.0.0.{counter}"
        res_taken = await db.execute(select(Device).where(Device.ip == candidate).where(Device.id != conflict_dev.id))
        if not res_taken.scalar_one_or_none():
            return candidate
        counter += 1


async def _resolve_ip_conflict(db, ip: str, dev):
    """Move any other device holding `ip` to a safe placeholder IP. Does NOT commit."""
    res_conflict = await db.execute(select(Device).where(Device.ip == ip).where(Device.id != dev.id))
    conflict_dev = res_conflict.scalar_one_or_none()
    if not conflict_dev:
        return

    conflict_dev.is_online = False
    conflict_dev.ip_placeholder = True
    safe_ip = await _find_safe_placeholder_ip(db, conflict_dev)
    if conflict_dev.ip != safe_ip:
        conflict_dev.ip = safe_ip
        await clear_observations(db, conflict_dev.id)
    await db.flush()
    logger.warning(f"Sync: Resolved IP conflict. Moved conflicting device {conflict_dev.id} to placeholder IP {conflict_dev.ip}")


def _fill_scanned_name(dev, hostname: str | None) -> None:
    """A name the scan found fills a device that has none yet, as Info-Refresh does; a known
    hostname and a name the user gave stay untouched."""
    if not hostname or is_ip_like(hostname) or not is_ip_like(dev.hostname):
        return
    dev.hostname = hostname
    if is_ip_like(dev.display_name):
        dev.display_name = hostname.split('.')[0]


def _refresh_device(dev, disc, hit: ScanHit) -> None:
    """The device answered: fill its gaps from the scan and mark it online."""
    _fill_scanned_name(dev, hit.hostname)
    _mark_seen(dev)
    dev.missed_scans = 0
    if hit.is_valid_mac and not _mac_is_valid(dev.mac):
        dev.mac = hit.mac
    if _should_apply_custom_name(disc, dev):
        dev.display_name = disc.custom_name


def _is_verified_ip_change(dev, hit: ScanHit, match_type: str | None) -> bool:
    same_mac = bool(hit.mac and dev.mac and dev.mac.lower() == hit.mac.lower())
    return bool(hit.is_valid_mac and same_mac and match_type in ("exact", "mac"))


def _record_verified_ip_change(db, dev, ctx: SyncContext) -> None:
    """Add the DeviceHistory entry and queue the webhook of an IP change just applied to `dev`."""
    db.add(DeviceHistory(
        device_id=dev.id,
        status="ip_changed",
        read=False,
        message=f"IP changed from {dev.old_ip} to {dev.ip}"
    ))
    ctx.pending_webhooks.append(("device.ip_changed", {
        "device_id": dev.id,
        "old_ip": dev.old_ip,
        "new_ip": dev.ip,
        "mac": dev.mac,
        "display_name": dev.display_name,
        "hostname": dev.hostname,
    }))


async def _move_device_to_scanned_ip(db, dev, hit: ScanHit, match_type: str | None, ctx: SyncContext) -> None:
    """Give `dev` the scanned address. Does NOT commit."""
    is_verified_change = _is_verified_ip_change(dev, hit, match_type)

    # To prevent UNIQUE constraint error on devices.ip:
    # check if another device already has the new IP.
    await _resolve_ip_conflict(db, hit.ip, dev)

    dev.old_ip = dev.ip
    dev.ip = hit.ip
    dev.ip_changed_at = datetime.now(timezone.utc)
    await clear_observations(db, dev.id)

    # ONLY emit DeviceHistory event if IP change is VERIFIED
    if is_verified_change:
        _record_verified_ip_change(db, dev, ctx)
    else:
        logger.info(f"Sync: Updated IP of device {dev.id} to {hit.ip} without DeviceHistory notification (unverified match).")


async def _update_dashboard_device(db, dev, disc, hit: ScanHit, match_type: str | None, ctx: SyncContext):
    """Apply cross-sync updates to a monitored Device. Does NOT commit."""
    if not dev:
        return
    if match_type == "ip" and _macs_conflict(dev.mac, hit.mac, hit.is_valid_mac):
        # Another valid MAC answered at this IP: record the conflict once, but do not confirm
        # the documented device as online, update last_seen/missed_scans, or adopt a foreign name.
        await record_mac_conflict(db, dev, hit.mac, "scan", ctx.reported_macs)
        return
    batch_macs = ctx.batch_macs_by_ip.get(dev.ip, ()) if dev.ip else ()
    batch_has_conflict = any(macs_differ(dev.mac, m) for m in batch_macs)
    if dev.ip == hit.ip and batch_has_conflict:
        # Both the documented MAC and a conflicting MAC were seen for this IP in the same pass:
        # treat the pass as ambiguous regardless of entry order (no confirmation, no auto-recovery).
        return
    if match_type == "exact":
        # Clean matching L2 sighting at the unchanged IP resolves open conflicts automatically.
        await clear_open_observations(db, dev.id)
    _refresh_device(dev, disc, hit)
    if dev.ip != hit.ip:
        await _move_device_to_scanned_ip(db, dev, hit, match_type, ctx)


def _keeps_ip_across_subnets(dev, ip: str, match_type: str | None, ctx: SyncContext) -> bool:
    """True when a MAC/hostname fallback hit in another subnet must not move the device.

    The same MAC in two subnets is the router pattern: a gateway of several VLANs
    answers on each of them. That is no IP change while the device is a known
    gateway/multi-homed box or still answers on its own address. A device that
    already went offline may still roam to another VLAN (old behaviour).
    """
    if match_type not in ("mac", "hostname") or dev.ip == ip:
        return False
    if not ctx.is_cross_segment(dev.ip, ip):
        return False
    if dev.interfaces or ctx.is_gateway(ip) or ctx.is_gateway(dev.ip):
        return True
    return bool(dev.is_online and not dev.ip_placeholder)


def _refresh_interface(iface, mac: str | None, is_valid_mac: bool, ctx: SyncContext) -> None:
    iface.is_online = True
    iface.missed_scans = 0
    iface.last_seen = datetime.now(timezone.utc)
    if is_valid_mac and not _mac_is_valid(iface.mac):
        iface.mac = mac
    if iface.subnet_id is None:
        sub = ctx.subnet_for(iface.ip)
        if sub:
            iface.subnet_id = sub.id


async def _attach_interface(db, dev, ip: str, mac: str | None, ctx: SyncContext):
    """Record `ip` as a further interface of `dev` (the gateway of another subnet). Does NOT commit."""
    sub = ctx.subnet_for(ip)
    iface = DeviceInterface(
        ip=ip, mac=mac,
        subnet_id=sub.id if sub else None,  # the VLAN tag is inherited from the subnet
        is_online=True,
        last_seen=datetime.now(timezone.utc),
    )
    dev.interfaces.append(iface)
    where = f" ({sub.name})" if sub else ""
    db.add(DeviceHistory(device_id=dev.id, status="info", message=f"Interface {ip}{where} attached"))
    await db.flush()
    logger.info("Sync: Attached gateway address %s as interface of device %s", ip, dev.id)
    return iface


async def _sync_interface_hit(db, iface, hit: ScanHit, ctx: SyncContext):
    """A scan answer from a known interface: refresh it, never move or create a Device."""
    _refresh_interface(iface, hit.mac, hit.is_valid_mac, ctx)
    dev = await db.get(Device, iface.device_id)
    disc = await _match_discovered_host(db, hit, ctx)
    return await _upsert_discovered_host(db, disc, dev, hit)


async def _sync_discovered(db, dev, match_type: str | None, hit: ScanHit, ctx: SyncContext):
    """Record the hit as a DiscoveredHost and carry it over to the matched Device, if any."""
    if dev is not None and dev.ip == hit.ip:
        batch_macs = ctx.batch_macs_by_ip.get(dev.ip, ())
        has_conflict = (match_type == "ip" and _macs_conflict(dev.mac, hit.mac, hit.is_valid_mac)) or any(
            macs_differ(dev.mac, m) for m in batch_macs
        )
        if has_conflict:
            # Conflicting or ambiguous L2 MAC at a monitored device's IP: record the conflict
            # on the device and leave DiscoveredHost untouched (matching the agent relay).
            await _update_dashboard_device(db, dev, None, hit, match_type, ctx)
            return None

    disc = await _match_discovered_host(db, hit, ctx)
    is_new_discovery = disc is None and dev is None

    disc = await _upsert_discovered_host(db, disc, dev, hit)
    if is_new_discovery and not ctx.is_initial:
        ctx.pending_webhooks.append(("new_device", {
            "ip": hit.ip,
            "mac": hit.mac,
            "hostname": hit.hostname,
            "vendor": hit.vendor,
            "first_seen": datetime.now(timezone.utc).isoformat(),
        }))

    await _update_dashboard_device(db, dev, disc, hit, match_type, ctx)
    return disc


async def _sync_second_address(db, dev, match_type: str | None, hit: ScanHit, ctx: SyncContext):
    """A device answered from another subnet: a gateway address becomes its interface."""
    if match_type == "mac" and hit.is_valid_mac and ctx.is_gateway(hit.ip):
        iface = await _attach_interface(db, dev, hit.ip, hit.mac, ctx)
        return await _sync_interface_hit(db, iface, hit, ctx)
    # Same box on a second address: leave it a separate discovered host, the
    # merge suggestions offer to make it an interface
    logger.info(
        "Sync: IP %s shares %s with device %s in another subnet; not treating as IP change",
        hit.ip,
        match_type,
        dev.id,
    )
    return await _sync_discovered(db, None, None, hit, ctx)


async def _sync_host_internal(db, host: dict, ctx: SyncContext | None = None):
    """
    Internal logic for syncing a single host. Does NOT commit.
    """
    hit = ScanHit.from_host(host)
    if ctx is None:
        ctx = await load_sync_context(db)

    # 0. A further address of a known device (e.g. a router's VLAN gateway)
    iface = await _query_by_ip(db, DeviceInterface, hit.ip) if hit.ip else None
    if iface:
        return await _sync_interface_hit(db, iface, hit, ctx)

    # 1. Dashboard Check (Is this host already monitored?)
    dev, match_type = await _match_dashboard_device(db, hit)
    if dev and _keeps_ip_across_subnets(dev, hit.ip, match_type, ctx):
        return await _sync_second_address(db, dev, match_type, hit, ctx)

    # 2. Discovery Table Deduplication and 3./4. updates of both tables
    return await _sync_discovered(db, dev, match_type, hit, ctx)


async def _sync_container_discovered(db, ip: str, container_name: str | None) -> None:
    """Mark the DiscoveredHost at the container's address online. Does NOT commit."""
    disc = await _query_by_ip(db, DiscoveredHost, ip)
    if not disc:
        return
    _mark_seen(disc)
    if not disc.custom_name or disc.custom_name == "Unknown":
        disc.custom_name = container_name


async def _sync_container_device(db, ip: str, container_name: str | None) -> None:
    """Mark the Device at the container's address online unless it has an open MAC conflict. Does NOT commit."""
    dev = await _query_by_ip(db, Device, ip)
    if not dev:
        return
    if await open_conflict_device_ids(db, (dev.id,)):
        return
    _mark_seen(dev)
    dev.missed_scans = 0
    logger.info(f"Docker Sync: Marked container {container_name} ({ip}) as ONLINE")


async def _sync_container_ip(db, ip: str, container_name: str | None):
    """Sync one container IP against DiscoveredHost and Device tables."""
    await _sync_container_discovered(db, ip, container_name)
    await _sync_container_device(db, ip, container_name)


async def sync_docker_containers(containers: list[dict]):
    """Mark the records at the addresses of running local containers as online.

    Only the address links a container to a record. A name never moves one: matching a
    container name as a substring of device names handed unrelated devices ("AP" in
    "grafana-api") over to container addresses, kept them online there and hid their
    outages. Placeholder records of containers are restored by name on start instead
    (app.database.migrations), with exact names only.
    """
    if not containers:
        return

    async with async_session() as db:
        for container in containers:
            ips = container.get("ips", [])
            is_running = container.get("status") == "running"
            container_name = container.get("name")

            if not ips or not is_running:
                continue

            for ip in ips:
                await _sync_container_ip(db, ip, container_name)

        await db.commit()
        discovery_cache.invalidate()
        dashboard_cache.invalidate_all()
        topology_cache.invalidate()
