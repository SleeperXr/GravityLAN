"""MAC addresses that answer at a device's address but are not its own, and the controlled MAC change.

An ARP answer or a scan hit at an address confirms an endpoint there, not the device documented at
it: after an IP is handed to another box, writing that box's MAC onto the device swapped the
identity for good. So neither the agent relay nor the scan changes a device's valid MAC. They
record what they saw (record_mac_conflict), once per device and MAC, and the user adopts it or
corrects the MAC by hand (set_device_mac), which keeps the device id and writes the history.

One MAC at several addresses (ipvlan containers sharing their host's MAC) is normal and never
recorded here; only a different valid MAC at a device's own address is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device, DeviceHistory, DeviceMacObservation, DiscoveredHost

_MAC_FORMAT = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")

OPEN = "open"
DISMISSED = "dismissed"


class MacChangeError(ValueError):
    """The MAC asked for cannot be set (not a unicast MAC address)."""


def normalise_mac(mac: str | None) -> str | None:
    """Lower case with colons, or None when ``mac`` is no MAC address."""
    if not mac:
        return None
    value = str(mac).strip().lower().replace("-", ":")
    return value if _MAC_FORMAT.match(value) else None


def is_usable_mac(mac: str | None) -> bool:
    """A unicast MAC that is not all zeros: what can stand for one network card."""
    value = normalise_mac(mac)
    if not value or value == "00:00:00:00:00:00":
        return False
    # The lowest bit of the first octet marks group addresses (multicast, broadcast)
    return int(value[:2], 16) & 1 == 0


def macs_differ(documented: str | None, observed: str | None) -> bool:
    """True when both are usable MACs and not the same one: a conflict, not a gap to fill."""
    return is_usable_mac(documented) and is_usable_mac(observed) and normalise_mac(documented) != normalise_mac(observed)


@dataclass
class ReportedPairs:
    """(device id, MAC) pairs handled in one pass.

    The sessions run without autoflush, so a second sighting in the same pass would not find the
    row added by the first and would insert it again.
    """

    pairs: set[tuple[int, str]] = field(default_factory=set)


async def record_mac_conflict(
    db: AsyncSession, device: Device, mac: str, source: str, reported: ReportedPairs | None = None,
) -> bool:
    """Note that ``mac`` answered at ``device``'s address; True when that is new and was reported.

    A known pair only moves ``last_seen``; a dismissed one stays quiet. Does NOT commit.
    """
    observed = normalise_mac(mac)
    # A group address (multicast, broadcast) is no card's MAC; the scan lets some through
    if not is_usable_mac(observed) or device.id is None:
        return False
    key = (device.id, observed)
    if reported is not None:
        if key in reported.pairs:
            return False
        reported.pairs.add(key)

    now = datetime.now(UTC)
    row = (await db.execute(
        select(DeviceMacObservation).where(
            DeviceMacObservation.device_id == device.id, DeviceMacObservation.observed_mac == observed,
        )
    )).scalar_one_or_none()
    if row is not None:
        if row.state == OPEN:
            row.last_seen = now
        return False

    # The relay and a scan run in sessions of their own: the other one may have added the same
    # pair since the lookup. A savepoint keeps that duplicate from taking the whole pass down.
    await db.flush()
    try:
        async with db.begin_nested():
            db.add(DeviceMacObservation(
                device_id=device.id, observed_mac=observed, source=source, first_seen=now, last_seen=now, state=OPEN,
            ))
    except IntegrityError:
        return False
    db.add(DeviceHistory(
        device_id=device.id,
        status="mac_conflict",
        read=False,
        message=f"Another MAC answers at {device.ip}: {observed} (device has {device.mac})"[:255],
    ))
    return True


async def _shared_targets(db: AsyncSession, device: Device, old: str, new: str) -> list[Device]:
    """Other devices with the same old MAC that saw the same new one (an ipvlan host's containers)."""
    rows = await db.execute(
        select(Device)
        .join(DeviceMacObservation, DeviceMacObservation.device_id == Device.id)
        .where(
            Device.id != device.id,
            func.lower(Device.mac) == old,
            DeviceMacObservation.observed_mac == new,
            DeviceMacObservation.state == OPEN,
        )
        .order_by(Device.id)
    )
    return list(rows.scalars().all())


async def _apply_mac(db: AsyncSession, device: Device, new: str, origin: str) -> bool:
    """Set ``new`` on the device (and its discovered host); True when the MAC changed. Does NOT commit."""
    previous = device.mac
    changed = normalise_mac(previous) != new
    if changed:
        disc = (await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == device.ip))).scalar_one_or_none()
        if disc is not None and (not is_usable_mac(disc.mac) or normalise_mac(disc.mac) == normalise_mac(previous)):
            disc.mac = new
        device.mac = new
        db.add(DeviceHistory(
            device_id=device.id,
            status="mac_changed",
            read=False,
            message=f"MAC changed from {previous or 'none'} to {new} ({origin})"[:255],
        ))
    observation = (await db.execute(
        select(DeviceMacObservation).where(
            DeviceMacObservation.device_id == device.id, DeviceMacObservation.observed_mac == new,
        )
    )).scalar_one_or_none()
    if observation is not None:
        await db.delete(observation)
    return changed


async def set_device_mac(
    db: AsyncSession, device: Device, mac: str, *, adopted: bool, apply_to_shared: bool = False,
) -> list[Device]:
    """Give ``device`` the MAC ``mac``, by hand or by adopting an observation; returns the devices changed.

    The device keeps its id and gets a ``mac_changed`` history entry. With ``apply_to_shared`` the
    devices that share the old MAC and saw the same new one get it too. Does NOT commit.
    """
    new = normalise_mac(mac)
    if not is_usable_mac(new):
        raise MacChangeError("Not a usable MAC address (six hex pairs, unicast, not all zeros).")
    old = normalise_mac(device.mac)
    origin = "adopted" if adopted else "manual"

    targets = [device]
    if apply_to_shared and old and old != new:
        targets += await _shared_targets(db, device, old, new)

    changed = []
    for target in targets:
        if await _apply_mac(db, target, new, origin):
            changed.append(target)
    return changed


async def has_open_observation(db: AsyncSession, device: Device, mac: str) -> bool:
    """Whether ``mac`` was seen at the device and is still waiting for a decision."""
    observed = normalise_mac(mac)
    if observed is None:
        return False
    row = (await db.execute(
        select(DeviceMacObservation.id).where(
            DeviceMacObservation.device_id == device.id,
            DeviceMacObservation.observed_mac == observed,
            DeviceMacObservation.state == OPEN,
        )
    )).first()
    return row is not None


async def dismiss_observation(db: AsyncSession, device: Device, mac: str) -> bool:
    """Keep the device's MAC and never report ``mac`` at it again; False when there is no such observation."""
    observed = normalise_mac(mac)
    row = (await db.execute(
        select(DeviceMacObservation).where(
            DeviceMacObservation.device_id == device.id, DeviceMacObservation.observed_mac == observed,
        )
    )).scalar_one_or_none()
    if row is None:
        return False
    row.state = DISMISSED
    return True


async def open_conflict_groups(db: AsyncSession) -> list[dict]:
    """Open observations grouped by (documented MAC, observed MAC), so one parent MAC change is one entry."""
    rows = (await db.execute(
        select(DeviceMacObservation, Device)
        .join(Device, Device.id == DeviceMacObservation.device_id)
        .where(DeviceMacObservation.state == OPEN)
        .order_by(DeviceMacObservation.first_seen, Device.id)
    )).all()
    groups: dict[tuple[str | None, str], dict] = {}
    for obs, dev in rows:
        key = (normalise_mac(dev.mac), obs.observed_mac)
        group = groups.setdefault(key, {
            "documented_mac": key[0],
            "observed_mac": key[1],
            "first_seen": obs.first_seen,
            "last_seen": obs.last_seen,
            "devices": [],
        })
        group["last_seen"] = max(group["last_seen"], obs.last_seen)
        group["devices"].append({
            "id": dev.id, "ip": dev.ip, "name": dev.display_name or dev.hostname or dev.ip, "source": obs.source,
        })
    return list(groups.values())
