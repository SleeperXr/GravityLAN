"""A different MAC at a device's address (app.services.mac_observations): the agent relay and the scan
never change a device's valid MAC, they record the sighting once; the user adopts it or corrects the
MAC by hand. One MAC at several addresses (ipvlan) is normal and never a conflict."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.api import backup
from app.models.agent import AgentConfig, AgentToken
from app.models.device import Device, DeviceHistory, DeviceMacObservation, DiscoveredHost
from app.models.network import Subnet
from app.scanner.sync import sync_hosts_batch
from app.services import mac_observations
from app.services.agent_scanner_relay import ingest_agent_arp_table

M1 = "02:00:00:00:00:01"
M2 = "02:00:00:00:00:02"
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
                patch("app.scanner.sync.detect_default_gateways", return_value=[]), \
                patch("app.services.webhook_service.trigger_webhooks", new=AsyncMock()):
            return await sync_hosts_batch(list(hosts))
    return run


@pytest.fixture
async def probe(db):
    dev = Device(ip="192.168.110.128", display_name="Probe", is_online=True)
    db.add(dev)
    await db.flush()
    db.add(AgentToken(device_id=dev.id, token="probe-token", is_active=True))
    db.add(AgentConfig(device_id=dev.id, enable_scanner_relay=True))
    db.add(Subnet(name="lan", cidr="192.168.110.0/24", is_enabled=True))
    await db.commit()
    return dev


@pytest.fixture
def relay(db, probe):
    async def run(*entries):
        return await ingest_agent_arp_table(db, probe.id, [{"ip": ip, "mac": mac} for ip, mac in entries])
    return run


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


async def add(db, *records):
    db.add_all(records)
    await db.commit()
    return records


async def observations(db):
    rows = (await db.execute(select(DeviceMacObservation).order_by(DeviceMacObservation.device_id))).scalars().all()
    return [(r.device_id, r.observed_mac, r.source, r.state) for r in rows]


async def history(db, status):
    rows = (await db.execute(select(DeviceHistory).where(DeviceHistory.status == status).order_by(DeviceHistory.id)))
    return rows.scalars().all()


def ipvlan_group(mac, *, adguard_mac=None, online=True):
    """An ipvlan host and two containers sharing its MAC; the last one may have no MAC yet."""
    return (
        Device(ip="192.168.110.5", mac=mac, display_name="Unraid", is_online=online),
        Device(ip="192.168.110.6", mac=mac, display_name="pihole", is_online=online),
        Device(ip="192.168.110.7", mac=adguard_mac if adguard_mac is not None else mac, display_name="adguard", is_online=online),
    )


# --- one MAC at several addresses (ipvlan) ---------------------------------------------------------

async def test_relay_accepts_one_mac_on_several_addresses(db, relay):
    devices = await add(db, *ipvlan_group(M1, adguard_mac=""))
    report = [(f"192.168.110.{n}", M1) for n in (5, 6, 7, 8)]

    await relay(*report)

    for dev in devices:
        await db.refresh(dev)
        assert dev.mac == M1
    new = (await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == "192.168.110.8"))).scalar_one()
    assert new.mac == M1
    await relay(*report)  # a repeat: still no conflict
    assert await observations(db) == []
    assert await history(db, "mac_conflict") == []


async def test_the_scan_takes_one_mac_on_several_addresses_without_a_conflict(db, scan):
    await add(db, *ipvlan_group(M1))
    await scan(*({"ip": f"192.168.110.{n}", "mac": M1} for n in (5, 6, 7)))
    assert await observations(db) == []


# --- the parent MAC changes, the addresses stay -----------------------------------------------------

async def test_parent_mac_change_is_one_open_observation_per_device_not_a_change(db, relay):
    devices = await add(db, *ipvlan_group(M1))

    for _ in range(3):  # three reports, 30 s apart
        await relay(*((d.ip, M2) for d in devices))

    for dev in devices:
        await db.refresh(dev)
        assert dev.mac == M1
    assert await observations(db) == [(d.id, M2, "relay", "open") for d in devices]
    assert len(await history(db, "mac_conflict")) == 3  # once per device, not per report


async def test_a_parent_mac_change_does_not_wake_an_offline_device(db, relay):
    (host,) = await add(db, Device(ip="192.168.110.5", mac=M1, display_name="Unraid", is_online=False, missed_scans=4))
    await relay(("192.168.110.5", M2))
    await db.refresh(host)
    assert (host.mac, host.is_online, host.missed_scans) == (M1, False, 4)


async def test_a_device_without_mac_in_the_group_is_filled_not_flagged(db, relay):
    devices = await add(db, *ipvlan_group(M1, adguard_mac=""))
    await relay(*((d.ip, M2) for d in devices))
    adguard = devices[2]
    await db.refresh(adguard)
    assert adguard.mac == M2
    assert [o[0] for o in await observations(db)] == [devices[0].id, devices[1].id]


async def test_conflicts_are_listed_as_one_group_per_mac_pair(db, relay, client, auth):
    devices = await add(db, *ipvlan_group(M1))
    await relay(*((d.ip, M2) for d in devices))

    response = await client.get("/api/devices/mac-conflicts", headers=auth)

    assert response.status_code == 200
    groups = response.json()
    assert [(g["documented_mac"], g["observed_mac"], [d["id"] for d in g["devices"]]) for g in groups] == [
        (M1, M2, [d.id for d in devices]),
    ]


async def test_adopting_the_observed_mac_for_the_group_keeps_ids_and_writes_history(db, relay, client, auth):
    devices = await add(db, *ipvlan_group(M1))
    ids = [d.id for d in devices]
    await relay(*((d.ip, M2) for d in devices))

    response = await client.put(f"/api/devices/{ids[1]}/mac", json={"mac": M2.upper(), "apply_to_shared": True}, headers=auth)

    assert response.status_code == 200
    assert sorted(response.json()["changed_device_ids"]) == ids
    for dev in devices:
        await db.refresh(dev)
        assert dev.mac == M2
    assert [d.id for d in (await db.execute(select(Device).where(Device.mac == M2))).scalars()] == ids
    changes = await history(db, "mac_changed")
    assert sorted(h.device_id for h in changes) == ids
    assert all("(adopted)" in h.message and M1 in h.message for h in changes)
    assert await observations(db) == []
    await relay(*((d.ip, M2) for d in devices))  # the adopted MAC is now the device's own
    assert await observations(db) == []
    assert len(await history(db, "mac_conflict")) == 3


async def test_adopting_for_one_device_leaves_the_others_open(db, relay, client, auth):
    devices = await add(db, *ipvlan_group(M1))
    await relay(*((d.ip, M2) for d in devices))

    response = await client.put(f"/api/devices/{devices[0].id}/mac", json={"mac": M2}, headers=auth)

    assert response.json()["changed_device_ids"] == [devices[0].id]
    assert [o[0] for o in await observations(db)] == [devices[1].id, devices[2].id]


# --- manual correction and dismissing --------------------------------------------------------------

async def test_a_manual_correction_needs_no_observation(db, client, auth):
    (server,) = await add(db, Device(ip="192.168.110.50", mac=MAC_A, display_name="Server"))
    disc = DiscoveredHost(ip="192.168.110.50", mac=MAC_A, is_monitored=True)
    await add(db, disc)

    response = await client.put(f"/api/devices/{server.id}/mac", json={"mac": "00-11-22-33-44-BB"}, headers=auth)

    assert response.status_code == 200
    await db.refresh(server)
    await db.refresh(disc)
    assert (server.id, server.mac, disc.mac) == (server.id, MAC_B, MAC_B)
    (entry,) = await history(db, "mac_changed")
    assert entry.message == f"MAC changed from {MAC_A} to {MAC_B} (manual)"


@pytest.mark.parametrize("mac", ["nonsense", "00:00:00:00:00:00", "01:00:5e:00:00:fb", "ff:ff:ff:ff:ff:ff"])
async def test_an_unusable_mac_is_refused(db, client, auth, mac):
    (server,) = await add(db, Device(ip="192.168.110.51", mac=MAC_A, display_name="Server"))
    response = await client.put(f"/api/devices/{server.id}/mac", json={"mac": mac}, headers=auth)
    assert response.status_code == 422
    await db.refresh(server)
    assert server.mac == MAC_A


async def test_the_mac_endpoints_need_an_admin(db, client):
    (server,) = await add(db, Device(ip="192.168.110.52", mac=MAC_A, display_name="Server"))
    assert (await client.put(f"/api/devices/{server.id}/mac", json={"mac": MAC_B})).status_code in (401, 403)
    assert (await client.get("/api/devices/mac-conflicts")).status_code in (401, 403)


async def test_a_dismissed_observation_is_not_reported_again_but_a_new_mac_is(db, relay, client, auth):
    (printer,) = await add(db, Device(ip="192.168.110.11", mac=MAC_A, display_name="Printer"))
    await relay(("192.168.110.11", MAC_B))

    response = await client.post(f"/api/devices/{printer.id}/mac-observations/dismiss", json={"mac": MAC_B}, headers=auth)
    assert response.status_code == 204
    await relay(("192.168.110.11", MAC_B))
    await relay(("192.168.110.11", "00:11:22:33:44:cc"))

    await db.refresh(printer)
    assert printer.mac == MAC_A
    assert await observations(db) == [
        (printer.id, MAC_B, "relay", "dismissed"), (printer.id, "00:11:22:33:44:cc", "relay", "open"),
    ]
    assert len(await history(db, "mac_conflict")) == 2
    assert (await client.get("/api/devices/mac-conflicts", headers=auth)).json()[0]["observed_mac"] == "00:11:22:33:44:cc"


async def test_dismissing_an_unknown_observation_is_404(db, client, auth):
    (printer,) = await add(db, Device(ip="192.168.110.12", mac=MAC_A, display_name="Printer"))
    response = await client.post(f"/api/devices/{printer.id}/mac-observations/dismiss", json={"mac": MAC_B}, headers=auth)
    assert response.status_code == 404


# --- the scan as a second source --------------------------------------------------------------------

async def test_ip_reuse_seen_by_the_relay_still_lets_the_scan_find_the_device_again(db, relay, scan):
    """The relay wrote the other box's MAC onto the NAS, and the scan then took it for the NAS for good."""
    (nas,) = await add(db, Device(ip="192.168.110.10", mac=MAC_A, display_name="NAS", is_online=False))

    await relay(("192.168.110.10", MAC_B))
    await scan({"ip": "192.168.110.10", "mac": MAC_B})
    await scan({"ip": "192.168.110.10", "mac": MAC_B}, {"ip": "192.168.110.20", "mac": MAC_A})

    await db.refresh(nas)
    assert (nas.ip, nas.mac) == ("192.168.110.20", MAC_A)
    assert len(await history(db, "ip_changed")) == 1
    assert len(await history(db, "mac_conflict")) == 1
    # Changed from keeping the stale IP-A observation open (AP 3.1): after moving to IP B,
    # observations from the old address are cleared while DeviceHistory keeps the audit trail.
    assert await observations(db) == []


async def test_the_scan_records_another_mac_at_a_device_once(db, scan):
    (server,) = await add(db, Device(ip="192.168.110.50", mac=MAC_A, display_name="Server", is_online=True))
    for _ in range(2):
        await scan({"ip": "192.168.110.50", "mac": MAC_B})
    await db.refresh(server)
    assert server.mac == MAC_A
    assert await observations(db) == [(server.id, MAC_B, "scan", "open")]
    assert len(await history(db, "mac_conflict")) == 1


async def test_the_same_conflict_twice_in_one_batch_is_one_row(db):
    (server,) = await add(db, Device(ip="192.168.110.53", mac=MAC_A, display_name="Server"))
    pairs = mac_observations.ReportedPairs()
    assert await mac_observations.record_mac_conflict(db, server, MAC_B, "scan", pairs) is True
    assert await mac_observations.record_mac_conflict(db, server, MAC_B.upper(), "scan", pairs) is False
    await db.commit()
    assert await observations(db) == [(server.id, MAC_B, "scan", "open")]


@pytest.mark.parametrize("group_mac", ["01:80:c2:00:00:00", "ff:ff:ff:ff:ff:ff"])
async def test_a_group_address_is_never_recorded(db, group_mac):
    """The scan's own check lets some group addresses through (only 01:00:5e and 33:33 are refused)."""
    (server,) = await add(db, Device(ip="192.168.110.54", mac=MAC_A, display_name="Server"))
    assert await mac_observations.record_mac_conflict(db, server, group_mac, "scan") is False
    await db.commit()
    assert await observations(db) == []


async def test_a_sighting_another_pass_saved_first_does_not_abort_this_pass(db, monkeypatch):
    """The relay and a scan run in their own sessions; the second insert of one pair must not fail the pass."""
    (server,) = await add(db, Device(ip="192.168.110.55", mac=MAC_A, display_name="Server", notes="before"))
    await add(db, DeviceMacObservation(device_id=server.id, observed_mac=MAC_B, source="relay",
                                       first_seen=datetime.now(UTC), last_seen=datetime.now(UTC)))
    real_execute = db.execute

    class NothingYet:
        def scalar_one_or_none(self):
            return None

    async def lookup_misses_the_other_pass(statement, *args, **kwargs):
        if "device_mac_observations" in str(statement) and statement.is_select:
            return NothingYet()  # the other pass committed after this one looked
        return await real_execute(statement, *args, **kwargs)

    server.notes = "changed in this pass"
    monkeypatch.setattr(db, "execute", lookup_misses_the_other_pass)
    assert await mac_observations.record_mac_conflict(db, server, MAC_B, "scan") is False
    monkeypatch.setattr(db, "execute", real_execute)
    await db.commit()

    await db.refresh(server)
    assert server.notes == "changed in this pass"
    assert await observations(db) == [(server.id, MAC_B, "relay", "open")]
    assert await history(db, "mac_conflict") == []


async def test_the_scan_records_a_parent_mac_change_for_each_device_once(db, scan):
    devices = await add(db, *ipvlan_group(M1))
    for _ in range(2):
        await scan(*({"ip": d.ip, "mac": M2} for d in devices))
    for dev in devices:
        await db.refresh(dev)
        assert dev.mac == M1
    assert await observations(db) == [(d.id, M2, "scan", "open") for d in devices]


# --- cleanup ----------------------------------------------------------------------------------------

async def test_deleting_a_device_removes_its_observations(db, relay, client, auth):
    (printer,) = await add(db, Device(ip="192.168.110.13", mac=MAC_A, display_name="Printer"))
    await relay(("192.168.110.13", MAC_B))

    assert (await client.delete(f"/api/devices/{printer.id}", headers=auth)).status_code == 204
    assert await observations(db) == []


def test_observations_of_reassigned_devices_go_on_restore_and_stay_out_of_the_export():
    assert "device_mac_observations" in backup.DEVICE_BOUND_DELETE
    assert "device_mac_observations" not in backup.ALLOWED_TABLE_MAP.values()


def test_a_restore_that_swaps_two_containers_sharing_a_mac_counts_both_as_reassigned():
    """The MAC alone cannot tell ipvlan containers apart: their agent tokens, history and sightings must go."""
    before = {1: (M1, "192.168.110.5"), 2: (M1, "192.168.110.6"), 3: (M1, "192.168.110.7")}
    after = {1: (M1, "192.168.110.6"), 2: (M1, "192.168.110.5"), 3: (M1, "192.168.110.7")}
    assert backup._reassigned_ids(before, after) == [1, 2]


def test_a_device_with_its_own_mac_may_change_its_address_in_a_restore():
    before = {1: (MAC_A, "192.168.110.10"), 2: (M1, "192.168.110.5"), 3: (M1, "192.168.110.6")}
    after = {1: (MAC_A, "192.168.110.99"), 2: (M1, "192.168.110.5"), 3: (M1, "192.168.110.6")}
    assert backup._reassigned_ids(before, after) == []


@pytest.mark.parametrize("mac, usable", [
    ("02:42:ac:11:00:02", True), ("AA-BB-CC-00-00-01", True), ("00:00:00:00:00:00", False),
    ("01:00:5e:00:00:fb", False), ("33:33:00:00:00:01", False), ("ff:ff:ff:ff:ff:ff", False), ("", False), (None, False),
])
def test_usable_mac(mac, usable):
    assert mac_observations.is_usable_mac(mac) is usable
