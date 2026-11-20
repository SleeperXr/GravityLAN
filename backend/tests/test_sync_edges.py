"""Edges of the scan sync (app/scanner/sync.py): records with gaps, MAC conflicts at a known IP,
several records behind one MAC, moved discovered hosts, commit retries and bad input."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.device import Device, DeviceHistory, DiscoveredHost
from app.models.network import Subnet
from app.scanner import sync
from app.scanner.sync import (
    SyncContext,
    commit_or_discard,
    _find_safe_placeholder_ip,
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


async def test_a_locked_commit_is_rolled_back_and_reported():
    db = SimpleNamespace(commit=AsyncMock(side_effect=locked()), rollback=AsyncMock())
    assert await commit_or_discard(db) == "locked"
    db.rollback.assert_awaited_once()


async def test_commit_raises_on_other_errors():
    db = SimpleNamespace(commit=AsyncMock(side_effect=locked("disk I/O error")), rollback=AsyncMock())
    with pytest.raises(OperationalError):
        await commit_or_discard(db)
    assert db.commit.await_count == 1


async def test_a_locked_batch_is_redone_not_committed_empty(db, scan):
    """The rollback after a lock drops the session's changes; the batch is applied again, so the host is saved."""
    real_commit = db.commit
    calls = 0

    async def commit_locked_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise locked()
        await real_commit()

    with patch.object(db, "commit", new=commit_locked_once), \
            patch("app.scanner.sync.asyncio.sleep", new=AsyncMock()) as sleep:
        await scan({"ip": "192.0.2.50", "mac": MAC_A})

    sleep.assert_awaited_once_with(0.2)
    saved = (await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == "192.0.2.50"))).scalar_one_or_none()
    assert saved is not None


async def test_a_lock_inside_one_host_redoes_the_batch_instead_of_skipping_the_host(db, scan):
    """A flush or DELETE can meet the lock before the commit; the host must not just be logged and dropped."""
    real = sync._sync_host_internal
    calls = 0

    async def locked_once(session, host, ctx):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise locked()
        return await real(session, host, ctx)

    with patch("app.scanner.sync._sync_host_internal", new=locked_once), \
            patch("app.scanner.sync.asyncio.sleep", new=AsyncMock()):
        results = await scan({"ip": "192.0.2.52", "mac": MAC_A})

    assert [r.ip for r in results] == ["192.0.2.52"]
    saved = (await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == "192.0.2.52"))).scalar_one_or_none()
    assert saved is not None


async def test_a_lock_after_staged_changes_redoes_the_whole_batch_in_a_new_session(db):
    """Host 1 stages its changes, host 2 meets the lock: the next attempt, in its own session,
    saves both, and each webhook goes out once (the first attempt's were never committed)."""
    real = sync._sync_host_internal
    calls = []
    sessions = []

    async def lock_second_host_once(session, host, ctx):
        calls.append(host["ip"])
        sessions.append(session)
        if host["ip"] == "192.0.2.62" and calls.count("192.0.2.62") == 1:
            raise locked()
        return await real(session, host, ctx)

    hooks = AsyncMock()
    # A real new session per attempt, on the test database
    new_session = async_sessionmaker(db.bind, expire_on_commit=False, autoflush=False)
    with patch("app.scanner.sync.async_session", new=new_session), \
            patch("app.scanner.sync.detect_default_gateways", return_value=[]), \
            patch("app.scanner.sync._sync_host_internal", new=lock_second_host_once), \
            patch("app.scanner.sync.asyncio.sleep", new=AsyncMock()), \
            patch("app.services.webhook_service.trigger_webhooks", new=hooks):
        results = await sync_hosts_batch([{"ip": "192.0.2.61", "mac": MAC_A}, {"ip": "192.0.2.62", "mac": MAC_B}])

    assert calls == ["192.0.2.61", "192.0.2.62", "192.0.2.61", "192.0.2.62"]
    assert sessions[0] is not sessions[2]
    assert sorted(r.ip for r in results) == ["192.0.2.61", "192.0.2.62"]
    saved = (await db.execute(select(DiscoveredHost.ip).where(DiscoveredHost.ip.in_(["192.0.2.61", "192.0.2.62"])))).scalars().all()
    assert sorted(saved) == ["192.0.2.61", "192.0.2.62"]
    sent = [(c.kwargs.get("event_type"), str(c.kwargs.get("data"))) for c in hooks.await_args_list]
    assert len(sent) == len(set(sent))


async def test_a_lock_while_loading_the_context_is_retried(db, scan):
    real = sync.load_sync_context
    calls = 0

    async def locked_once(session):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise locked("database is busy")
        return await real(session)

    with patch("app.scanner.sync.load_sync_context", new=locked_once), \
            patch("app.scanner.sync.asyncio.sleep", new=AsyncMock()):
        await scan({"ip": "192.0.2.63", "mac": MAC_A})

    assert calls == 2
    saved = (await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == "192.0.2.63"))).scalar_one_or_none()
    assert saved is not None


async def test_a_batch_that_stays_locked_raises_and_sends_no_webhooks(db, scan):
    commit = AsyncMock(side_effect=locked())
    with patch.object(db, "commit", new=commit), \
            patch("app.scanner.sync.asyncio.sleep", new=AsyncMock()), \
            patch("app.services.webhook_service.trigger_webhooks", new=AsyncMock()) as hooks, \
            pytest.raises(OperationalError):
        await scan({"ip": "192.0.2.51", "mac": MAC_B})
    assert commit.await_count == sync.BATCH_ATTEMPTS
    hooks.assert_not_awaited()


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


async def test_mac_match_ignores_case_of_older_relay_rows(db, scan):
    """The agent relay used to store upper-case MACs; the scanner reports lower case."""
    owner = DiscoveredHost(ip="192.0.2.40", mac=MAC_A.upper(), is_online=False)
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


PI_HIT = {"ip": "192.0.2.10", "mac": MAC_A, "hostname": "raspberrypi"}


async def add_documented_pi(db, is_online=True):
    dev = Device(ip="192.0.2.10", mac=MAC_A, hostname="raspberrypi", display_name="Pi-hole",
                 notes="DNS", is_online=is_online)
    disc = DiscoveredHost(ip="192.0.2.10", mac=MAC_A, hostname="raspberrypi", custom_name="Pi-hole",
                          is_online=is_online, is_monitored=True)
    await add(db, dev, disc)
    return dev, disc


async def ip_changes(db):
    return (await db.execute(select(DeviceHistory).where(DeviceHistory.status == "ip_changed"))).scalars().all()


@pytest.mark.parametrize("other_ip, other_first", [("192.0.2.50", False), ("192.0.2.5", True)])
async def test_same_name_with_another_mac_does_not_take_over_the_device(db, scan, other_ip, other_first):
    """A second box with the same hostname took over the record, its notes and probes, and in
    every later scan the MAC match pulled it back: an ip_changed event per scan, and the second
    box never got a record of its own."""
    dev, disc = await add_documented_pi(db)
    other = {"ip": other_ip, "mac": MAC_B, "hostname": "raspberrypi"}
    batch = (other, PI_HIT) if other_first else (PI_HIT, other)

    for _ in range(2):
        await scan(*batch)

    await db.refresh(dev)
    await db.refresh(disc)
    assert (dev.ip, dev.mac, dev.old_ip, dev.notes) == ("192.0.2.10", MAC_A, None, "DNS")
    assert (disc.ip, disc.mac) == ("192.0.2.10", MAC_A)
    assert await ip_changes(db) == []
    candidate = (await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == other_ip))).scalar_one()
    assert (candidate.mac, candidate.hostname, candidate.is_monitored) == (MAC_B, "raspberrypi", False)


async def test_same_name_with_another_mac_leaves_an_offline_device_where_it_is(db, scan):
    """The other box must not make the documented one look online at its address."""
    dev, _ = await add_documented_pi(db, is_online=False)

    await scan({"ip": "192.0.2.50", "mac": MAC_B, "hostname": "raspberrypi"})

    await db.refresh(dev)
    assert (dev.ip, dev.is_online, dev.old_ip) == ("192.0.2.10", False, None)
    candidate = (await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == "192.0.2.50"))).scalar_one()
    assert (candidate.mac, candidate.is_monitored) == (MAC_B, False)


async def test_a_user_given_name_does_not_pull_in_another_box_with_that_hostname(db, scan):
    nas = Device(ip="192.0.2.20", mac=MAC_A, hostname="ds920.lan", display_name="nas", is_online=True)
    await add(db, nas)

    await scan({"ip": "192.0.2.60", "mac": MAC_B, "hostname": "nas"})

    await db.refresh(nas)
    assert (nas.ip, nas.old_ip) == ("192.0.2.20", None)


@pytest.mark.parametrize("model", [Device, DiscoveredHost])
async def test_name_match_is_literal_not_a_like_pattern(db, scan, model):
    """With ilike, "_" in a scanned name matched any character of a stored one."""
    fields = {"display_name": "Sensor"} if model is Device else {}
    record = model(ip="192.0.2.30", mac=None, hostname="esp-01", is_online=False, **fields)
    await add(db, record)

    await scan({"ip": "192.0.2.70", "mac": None, "hostname": "esp_01"})

    await db.refresh(record)
    assert record.ip == "192.0.2.30"


async def test_name_match_ignores_case(db, scan):
    known = DiscoveredHost(ip="192.0.2.62", mac=None, hostname="Camera", is_online=False)
    await add(db, known)
    await scan({"ip": "192.0.2.63", "mac": None, "hostname": "camera"})
    await db.refresh(known)
    assert known.ip == "192.0.2.63"


async def test_device_name_still_follows_a_dhcp_move_without_any_mac(db, scan):
    dev = Device(ip="192.0.2.40", mac=None, hostname="camera", display_name="Camera", is_online=False)
    await add(db, dev)

    await scan({"ip": "192.0.2.41", "mac": None, "hostname": "camera"})

    await db.refresh(dev)
    assert (dev.ip, dev.old_ip) == ("192.0.2.41", "192.0.2.40")


async def test_a_hit_without_mac_still_follows_the_name_of_a_device_with_one(db, scan):
    """Accepted on purpose: a routed scan sees no MAC, so nothing contradicts the name."""
    dev = Device(ip="192.0.2.42", mac=MAC_A, hostname="camera", display_name="Camera", is_online=False)
    await add(db, dev)

    await scan({"ip": "192.0.2.43", "mac": None, "hostname": "camera"})

    await db.refresh(dev)
    assert (dev.ip, dev.mac) == ("192.0.2.43", MAC_A)


async def test_placeholder_prefers_a_free_old_ip_and_otherwise_counts_up(db):
    taken = Device(ip="0.0.0.0", display_name="placeholder")
    moved = Device(ip="192.0.2.70", old_ip="192.0.2.71", display_name="moved")
    offline = Device(ip="192.0.2.72", old_ip="offline-1", display_name="offline")
    await add(db, taken, moved, offline)
    assert await _find_safe_placeholder_ip(db, moved) == "192.0.2.71"
    assert await _find_safe_placeholder_ip(db, offline) == "0.0.0.1"


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


@pytest.fixture
def docker(db):
    async def run(*containers):
        with patch("app.scanner.sync.async_session", return_value=Session(db)):
            await sync_docker_containers(list(containers))
    return run


def running(name, ip):
    return {"name": name, "ips": [ip], "status": "running"}


@pytest.mark.parametrize("is_online", [True, False])
async def test_a_container_name_containing_a_device_name_does_not_take_the_device(db, docker, scan, is_online):
    """"AP" is part of "grafana-api": the AP was moved to the container's bridge address, marked online there
    (also while it was down), and a scan that saw it at its own address made that a second host."""
    ap = Device(ip="192.0.2.2", mac=MAC_A, display_name="AP", is_online=is_online, missed_scans=0 if is_online else 5)
    await add(db, ap)

    await docker(running("grafana-api", "172.18.0.5"))
    if is_online:
        await scan({"ip": "192.0.2.2", "mac": MAC_A})

    await db.refresh(ap)
    assert (ap.ip, ap.old_ip, ap.is_online) == ("192.0.2.2", None, is_online)


async def test_a_container_in_the_lan_does_not_take_a_live_device_with_a_similar_name(db, docker, scan):
    """Same subnet: every scan pulled the device back by its MAC, reported an IP change, and lost it again."""
    nextcloud = Device(ip="192.0.2.30", mac=MAC_A, display_name="Nextcloud", is_online=True)
    await add(db, nextcloud)

    for _ in range(2):
        await docker(running("nextcloud-db", "192.0.2.70"))
        await scan({"ip": "192.0.2.30", "mac": MAC_A}, {"ip": "192.0.2.70", "mac": MAC_B})

    await db.refresh(nextcloud)
    assert (nextcloud.ip, nextcloud.old_ip) == ("192.0.2.30", None)
    assert (await db.execute(select(DeviceHistory).where(DeviceHistory.status == "ip_changed"))).first() is None
    container = (await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == "192.0.2.70"))).scalar_one()
    assert container.mac == MAC_B


async def test_a_device_at_the_container_address_is_not_pushed_aside(db, docker):
    printer = Device(ip="192.0.2.60", mac=MAC_B, display_name="Printer", is_online=False)
    pi = Device(ip="192.0.2.40", mac=MAC_A, display_name="Pi", is_online=True)
    await add(db, printer, pi)

    # The container runs at the printer's address: before, "Pi" was moved there and the printer
    # pushed aside to a 0.0.0.N placeholder
    await docker(running("pi-backup", "192.0.2.60"))

    await db.refresh(printer)
    await db.refresh(pi)
    assert (printer.ip, printer.ip_placeholder, printer.old_ip) == ("192.0.2.60", False, None)
    assert (pi.ip, pi.old_ip) == ("192.0.2.40", None)


async def test_a_container_without_a_record_at_its_address_changes_nothing(db, docker):
    disc = DiscoveredHost(ip="192.0.2.91", hostname="plex", custom_name="Unknown", is_online=False)
    await add(db, disc)

    await docker(running("plex", "192.0.2.92"))

    await db.refresh(disc)
    assert (disc.ip, disc.is_online, disc.custom_name) == ("192.0.2.91", False, "Unknown")


async def test_no_containers_is_a_no_op():
    with patch("app.scanner.sync.async_session") as session:
        await sync_docker_containers([])
    session.assert_not_called()
