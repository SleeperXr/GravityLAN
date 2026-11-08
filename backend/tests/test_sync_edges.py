"""Edges of the scan sync (app/scanner/sync.py): records with gaps, MAC conflicts at a known IP,
several records behind one MAC, moved discovered hosts, commit retries and bad input."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.models.device import Device, DiscoveredHost
from app.models.network import Subnet
from app.scanner import sync
from app.scanner.sync import (
    SyncContext,
    _commit_with_retry,
    _find_safe_placeholder_ip,
    _relocate_conflicting_device,
    _should_apply_custom_name,
    _sync_host_internal,
    load_sync_context,
    sync_docker_containers,
    sync_hosts_batch,
)

MAC_A = "00:11:22:33:44:aa"
MAC_B = "00:11:22:33:44:bb"


class Session:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def scan(db):
    async def run(*hosts):
        with patch("app.scanner.sync.async_session", return_value=Session(db)), \
                patch("app.scanner.sync.detect_default_gateways", return_value=[]):
            return await sync_hosts_batch(list(hosts))
    return run


def locked(message="database is locked"):
    return OperationalError("COMMIT", {}, Exception(message))


async def add(db, *records):
    db.add_all(records)
    await db.commit()


def test_context_treats_non_addresses_as_unknown():
    ctx = SyncContext()
    assert ctx.subnet_for("not-an-ip") is None
    assert ctx.subnet_for(None) is None
    assert ctx.segment("not-an-ip") is None
    assert ctx.segment("192.0.2.9") == "192.0.2.0/24"
    assert ctx.is_cross_segment("not-an-ip", "192.0.2.9") is False


async def test_context_skips_an_invalid_subnet(db):
    await add(db, Subnet(cidr="not-a-network", name="broken"), Subnet(cidr="192.0.2.0/24", name="lan"))
    with patch("app.scanner.sync.detect_default_gateways", return_value=[]):
        ctx = await load_sync_context(db)
    assert [str(net) for net, _ in ctx.networks] == ["192.0.2.0/24"]


def test_custom_name_needs_a_discovery_with_a_name_and_a_nameless_device():
    nameless = SimpleNamespace(display_name="Unknown")
    assert _should_apply_custom_name(None, nameless) is False
    assert _should_apply_custom_name(SimpleNamespace(custom_name=None), nameless) is False
    assert _should_apply_custom_name(SimpleNamespace(custom_name="NAS"), nameless) is True
    assert _should_apply_custom_name(SimpleNamespace(custom_name="NAS"), SimpleNamespace(display_name="Mine")) is False


async def test_commit_retries_while_the_database_is_locked():
    db = SimpleNamespace(commit=AsyncMock(side_effect=[locked(), None]), rollback=AsyncMock())
    with patch("app.scanner.sync.asyncio.sleep", new=AsyncMock()) as sleep:
        assert await _commit_with_retry(db) is True
    sleep.assert_awaited_once_with(0.2)
    db.rollback.assert_awaited_once()


async def test_commit_raises_on_other_errors_and_when_retries_run_out():
    db = SimpleNamespace(commit=AsyncMock(side_effect=locked("disk I/O error")), rollback=AsyncMock())
    with pytest.raises(OperationalError):
        await _commit_with_retry(db)
    assert db.commit.await_count == 1

    db = SimpleNamespace(commit=AsyncMock(side_effect=locked()), rollback=AsyncMock())
    with patch("app.scanner.sync.asyncio.sleep", new=AsyncMock()), pytest.raises(OperationalError):
        await _commit_with_retry(db)
    assert db.commit.await_count == 5


async def test_one_failing_host_does_not_stop_the_batch(db, scan):
    real = sync._sync_host_internal

    async def fail_first(session, host, ctx):
        if host["ip"] == "192.0.2.1":
            raise ValueError("bad host")
        return await real(session, host, ctx)

    with patch("app.scanner.sync._sync_host_internal", new=fail_first):
        results = await scan({"ip": "192.0.2.1", "mac": MAC_A}, {"ip": "192.0.2.2", "mac": MAC_B})
    assert [r.ip for r in results] == ["192.0.2.2"]


async def test_loads_the_context_itself_when_called_without_one(db):
    with patch("app.scanner.sync.detect_default_gateways", return_value=[]):
        disc = await _sync_host_internal(db, {"ip": "192.0.2.3", "mac": MAC_A})
    assert disc.ip == "192.0.2.3"


async def test_device_at_the_ip_gets_its_gaps_filled(db, scan):
    dev = Device(ip="192.0.2.10", mac=None, display_name="Unknown", ip_placeholder=True, is_online=False, missed_scans=3)
    disc = DiscoveredHost(ip="192.0.2.10", mac=None, custom_name="Backup NAS", ip_placeholder=True, is_online=False)
    await add(db, dev, disc)

    await scan({"ip": "192.0.2.10", "mac": MAC_A, "vendor": "Acme", "ports": [22, 443]})
    await db.refresh(dev)
    await db.refresh(disc)

    assert (dev.mac, dev.display_name, dev.ip_placeholder, dev.is_online, dev.missed_scans) == (MAC_A, "Backup NAS", False, True, 0)
    assert (disc.mac, disc.vendor, disc.ports, disc.ip_placeholder, disc.is_online) == (MAC_A, "Acme", "[22, 443]", False, True)


async def test_ip_match_stands_when_no_record_holds_the_scanned_mac(db, scan):
    dev = Device(ip="192.0.2.20", mac=MAC_B, display_name="Printer")
    await add(db, dev)
    await scan({"ip": "192.0.2.20", "mac": MAC_A})
    await db.refresh(dev)
    assert (dev.ip, dev.mac) == ("192.0.2.20", MAC_B)


async def test_ip_match_stands_when_an_unraid_host_holds_the_mac(db, scan):
    container = Device(ip="192.0.2.30", mac=MAC_B, display_name="Container")
    host = Device(ip="192.0.2.31", mac=MAC_A, display_name="Tower", hostname="unraid")
    await add(db, container, host)
    await scan({"ip": "192.0.2.30", "mac": MAC_A})
    await db.refresh(container)
    await db.refresh(host)
    assert (container.ip, host.ip) == ("192.0.2.30", "192.0.2.31")
    assert container.old_ip is None


async def test_rejected_ip_match_moves_the_mac_owner_and_removes_the_stale_record(db, scan):
    owner = DiscoveredHost(ip="192.0.2.40", mac=MAC_A, is_online=False)
    stale = DiscoveredHost(ip="192.0.2.41", mac=MAC_B, is_online=False)
    await add(db, owner, stale)
    owner_id = owner.id

    await scan({"ip": "192.0.2.41", "mac": MAC_A})

    rows = (await db.execute(select(DiscoveredHost))).scalars().all()
    assert [(r.id, r.ip) for r in rows] == [(owner_id, "192.0.2.41")]


async def test_occupied_address_stands_when_the_mac_owner_is_live_in_another_subnet(db, scan):
    """A second row at the address broke the unique IP and lost the whole scan batch."""
    router = DiscoveredHost(ip="192.0.2.1", mac=MAC_A, is_online=True)
    occupant = DiscoveredHost(ip="198.51.100.5", mac=MAC_B, custom_name="Old printer", is_online=False)
    await add(db, router, occupant)

    results = await scan({"ip": "198.51.100.5", "mac": MAC_A}, {"ip": "192.0.2.77", "mac": "00:11:22:33:44:cc"})

    assert sorted(r.ip for r in results) == ["192.0.2.77", "198.51.100.5"]
    await db.refresh(router)
    await db.refresh(occupant)
    assert (router.ip, router.mac) == ("192.0.2.1", MAC_A)
    assert (occupant.ip, occupant.mac, occupant.custom_name, occupant.is_online) == ("198.51.100.5", MAC_B, "Old printer", True)
    rows = (await db.execute(select(DiscoveredHost.ip).order_by(DiscoveredHost.ip))).scalars().all()
    assert rows == ["192.0.2.1", "192.0.2.77", "198.51.100.5"]


async def test_several_devices_behind_one_mac_are_no_mac_match(db, scan):
    await add(
        db,
        Device(ip="192.0.2.50", mac=MAC_A, display_name="c1"),
        Device(ip="192.0.2.51", mac=MAC_A, display_name="c2"),
        DiscoveredHost(ip="192.0.2.50", mac=MAC_A),
        DiscoveredHost(ip="192.0.2.51", mac=MAC_A),
    )
    await scan({"ip": "192.0.2.52", "mac": MAC_A})

    devices = (await db.execute(select(Device.ip).order_by(Device.ip))).scalars().all()
    assert devices == ["192.0.2.50", "192.0.2.51"]
    discovered = (await db.execute(select(DiscoveredHost.ip).order_by(DiscoveredHost.ip))).scalars().all()
    assert discovered == ["192.0.2.50", "192.0.2.51", "192.0.2.52"]


async def test_discovered_host_is_found_again_by_name(db, scan):
    known = DiscoveredHost(ip="192.0.2.60", mac=None, hostname="camera", is_online=False)
    await add(db, known)
    await scan({"ip": "192.0.2.61", "mac": None, "hostname": "camera"})
    await db.refresh(known)
    assert known.ip == "192.0.2.61"


async def test_placeholder_prefers_a_free_old_ip_and_otherwise_counts_up(db):
    taken = Device(ip="0.0.0.0", display_name="placeholder")
    moved = Device(ip="192.0.2.70", old_ip="192.0.2.71", display_name="moved")
    offline = Device(ip="192.0.2.72", old_ip="offline-1", display_name="offline")
    await add(db, taken, moved, offline)
    assert await _find_safe_placeholder_ip(db, moved) == "192.0.2.71"
    assert await _find_safe_placeholder_ip(db, offline) == "0.0.0.1"


async def test_relocating_a_device_uses_the_first_free_placeholder(db):
    holder = Device(ip="192.0.2.80", display_name="holder", is_online=True)
    await add(db, holder)
    used = {"0.0.0.0", "192.0.2.80"}
    await _relocate_conflicting_device(db, "192.0.2.80", used)
    assert (holder.ip, holder.is_online, holder.ip_placeholder) == ("0.0.0.1", False, True)
    assert "0.0.0.1" in used

    await _relocate_conflicting_device(db, "192.0.2.99", used)  # nobody holds it
    assert used == {"0.0.0.0", "192.0.2.80", "0.0.0.1"}


async def test_running_container_at_a_known_ip_comes_online(db):
    disc = DiscoveredHost(ip="192.0.2.90", is_online=False, custom_name="Unknown", ip_placeholder=True)
    dev = Device(ip="192.0.2.90", display_name="web", is_online=False, missed_scans=2, ip_placeholder=True,
                 last_seen=datetime(2026, 1, 1, tzinfo=timezone.utc))
    await add(db, disc, dev)

    with patch("app.scanner.sync.async_session", return_value=Session(db)):
        await sync_docker_containers([{"ips": ["192.0.2.90"], "status": "running", "name": "web"}])
    await db.refresh(disc)
    await db.refresh(dev)

    assert (disc.is_online, disc.custom_name, disc.ip_placeholder) == (True, "web", False)
    assert (dev.is_online, dev.missed_scans, dev.ip_placeholder, dev.ip) == (True, 0, False, "192.0.2.90")


async def test_no_containers_is_a_no_op():
    with patch("app.scanner.sync.async_session") as session:
        await sync_docker_containers([])
    session.assert_not_called()
