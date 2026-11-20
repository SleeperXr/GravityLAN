"""Service for ingesting Layer-2 ARP neighbors relayed by deployed agents."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig
from app.models.device import Device, DiscoveredHost
from app.models.network import Subnet
from app.scanner.vendor import get_vendor
from app.services.mac_observations import ReportedPairs, is_usable_mac, macs_differ, record_mac_conflict

logger = logging.getLogger(__name__)

ProbeNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def is_valid_mac_address(mac: str | None) -> bool:
    """A colon-separated unicast MAC that is not all zeros (multicast and broadcast are no card's MAC)."""
    if not mac or len(mac) != 17 or mac.count(":") != 5:
        return False
    return is_usable_mac(mac)


async def get_probe_networks(db: AsyncSession, device_id: int) -> list[ProbeNetwork]:
    """Return the configured subnets a device may relay ARP neighbors for.

    Empty unless the device has the scanner relay enabled. Like the probe
    badge in ``app.api.network._enrich_subnet``, a probe covers every
    configured subnet that contains its own IP.
    """
    relay_enabled = (await db.execute(
        select(AgentConfig.enable_scanner_relay).where(AgentConfig.device_id == device_id)
    )).scalar_one_or_none()
    if not relay_enabled:
        return []

    device = await db.get(Device, device_id)
    try:
        probe_addr = ipaddress.ip_address(device.ip) if device else None
    except ValueError:
        probe_addr = None
    if probe_addr is None:
        return []

    networks: list[ProbeNetwork] = []
    # Only the networks the scan itself sweeps: a paused one must not be updated by a relay either
    for cidr in (await db.execute(select(Subnet.cidr).where(Subnet.is_enabled.is_(True)))).scalars():
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue
        if probe_addr in net:
            networks.append(net)
    return networks


async def ingest_agent_arp_table(
    db: AsyncSession,
    reporting_device_id: int,
    arp_entries: list[Any],
) -> int:
    """Ingest ARP table reported by an agent probe.

    Only devices with the scanner relay enabled are heard, and only for
    addresses inside their own subnets (see ``get_probe_networks``), so one
    agent token cannot rewrite MAC, vendor or online state elsewhere.

    An ARP answer confirms an endpoint at an address, not the device documented there: a
    missing MAC is filled, but a different valid MAC changes neither the MAC nor the online
    state; it is recorded once as an observation (app.services.mac_observations). One MAC at
    several addresses (ipvlan) is normal. New addresses become discovered hosts.
    Returns the number of ingested/updated hosts.
    """
    if not arp_entries:
        return 0

    probe_networks = await get_probe_networks(db, reporting_device_id)
    if not probe_networks:
        logger.debug(
            f"Ignoring ARP table from device {reporting_device_id}: "
            "scanner relay disabled or no configured subnet contains the device"
        )
        return 0

    now = datetime.now(timezone.utc)
    updated_count = 0
    conflicts_seen = False  # only last_seen of an observation may have moved: commit, but no broadcast
    reported = ReportedPairs()
    out_of_scope: list[str] = []

    # Cache existing devices by IP
    dev_res = await db.execute(select(Device))
    devices_by_ip = {d.ip: d for d in dev_res.scalars().all()}

    # Cache existing discovered hosts by IP
    disc_res = await db.execute(select(DiscoveredHost))
    disc_by_ip = {h.ip: h for h in disc_res.scalars().all()}

    for entry in arp_entries:
        raw_ip = entry.get("ip") if isinstance(entry, dict) else getattr(entry, "ip", None)
        raw_mac = entry.get("mac") if isinstance(entry, dict) else getattr(entry, "mac", None)

        if not raw_ip or not raw_mac:
            continue

        raw_ip = str(raw_ip).strip()
        # Lower case, like the local scanner (arp.py), so sync.py's MAC matching
        # finds the same host whichever path saw it first
        raw_mac = str(raw_mac).strip().replace("-", ":").lower()

        try:
            addr = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue

        if not any(addr in net for net in probe_networks):
            out_of_scope.append(raw_ip)
            continue

        if not is_valid_mac_address(raw_mac):
            continue

        # 1. If device exists on dashboard, enrich MAC and online status
        if raw_ip in devices_by_ip:
            dev = devices_by_ip[raw_ip]
            if macs_differ(dev.mac, raw_mac):
                # Another box answers at this address: the device stays as it is
                conflicts_seen = True
                if await record_mac_conflict(db, dev, raw_mac, "relay", reported):
                    updated_count += 1
                continue
            changed = False
            if not is_usable_mac(dev.mac):
                dev.mac = raw_mac
                changed = True
            if not dev.vendor:
                dev.vendor = await asyncio.to_thread(get_vendor, raw_mac)
                changed = True
            if not dev.is_online and not dev.has_agent:
                dev.is_online = True
                dev.last_seen = now
                # Back online starts the miss count again, as a scan does (register_seen); the
                # old count made a single missed scan take it offline at once
                dev.missed_scans = 0
                changed = True
            if changed:
                updated_count += 1
            continue

        # 2. Update or insert DiscoveredHost
        if raw_ip in disc_by_ip:
            disc = disc_by_ip[raw_ip]
            if macs_differ(disc.mac, raw_mac):
                continue  # another box at this address: the record keeps its MAC and state
            if not is_usable_mac(disc.mac):
                disc.mac = raw_mac
            if not disc.vendor:
                disc.vendor = await asyncio.to_thread(get_vendor, raw_mac)
            disc.is_online = True
            disc.last_seen = now
            updated_count += 1
        else:
            new_disc = DiscoveredHost(
                ip=raw_ip,
                mac=raw_mac,
                vendor=await asyncio.to_thread(get_vendor, raw_mac),
                is_online=True,
                first_seen=now,
                last_seen=now,
            )
            db.add(new_disc)
            disc_by_ip[raw_ip] = new_disc
            updated_count += 1

    if out_of_scope:
        logger.debug(
            f"Agent probe {reporting_device_id}: ignored {len(out_of_scope)} ARP entries "
            f"outside its subnets: {', '.join(out_of_scope)}"
        )

    if updated_count == 0 and conflicts_seen:
        await db.commit()
    if updated_count > 0:
        await db.commit()
        logger.info(f"Agent probe {reporting_device_id} updated {updated_count} L2 neighbors.")
        try:
            from app.api.scanner import state as scan_state
            from app.schemas.scan import ScanProgress, ScanStatus
            await scan_state.broadcast(ScanProgress(
                status=ScanStatus.COMPLETED,
                current_subnet="",
                hosts_scanned=updated_count,
                hosts_total=updated_count,
                devices_found=updated_count,
                message=f"Agent probe {reporting_device_id} updated {updated_count} L2 neighbors",
                timestamp=now,
            ))
        except Exception as e:
            logger.debug(f"Could not broadcast scan progress from agent relay: {e}")

    return updated_count
