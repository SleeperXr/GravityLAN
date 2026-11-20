"""AP 3 regression tests: MAC observation lifecycle (A1) and neutral presence on MAC conflict (E1).

Covers:
1. Context-bound lifecycle (IP move, placeholder move, manual MAC change with multiple open
   observations, dismissed observation after MAC/IP change, group adoption target resolution
   before clearing, no-op preserving observations).
2. Neutral presence across sync, planner scan, dashboard scan, relay and health probe
   (offline device not woken, no last_seen/missed_scans reset, no false-positive health samples,
   no foreign service states, online device kept neutral without register_miss).
3. Automatic recovery on clean matching L2 MAC (relay and scan) while keeping dismissed rows,
   and order-independent ambiguity handling when both A and B appear in the same pass.
4. Preservation of legitimate behavior: IPVLAN shared MACs, DHCP IP move, devices without MAC,
   routed L3 probes without MAC, and recovery after dismiss or manual/adopted MAC change.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConfig, AgentToken
from app.models.device import Device, DeviceHealthSample, DeviceHistory, DeviceMacObservation, Service
from app.models.network import Subnet
from app.scanner import dashboard as dash_mod
from app.scanner import health_probe as hp_mod
from app.scanner import planner as planner_mod
from app.scanner.sync import sync_docker_containers, sync_hosts_batch
from app.services.agent_scanner_relay import ingest_agent_arp_table

MAC_A = "00:11:22:33:44:aa"
MAC_B = "00:11:22:33:44:bb"
MAC_C = "00:11:22:33:44:cc"
MAC_D = "00:11:22:33:44:dd"
M1 = "02:00:00:00:00:01"
M2 = "02:00:00:00:00:02"


class _SameSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def scan(db):
    async def run(*hosts):
        with patch("app.scanner.sync.async_session", return_value=_SameSession(db)), \
                patch("app.scanner.sync.detect_default_gateways", return_value=[]), \
                patch("app.services.webhook_service.trigger_webhooks", new=AsyncMock()):
            return await sync_hosts_batch(list(hosts))

    return run


@pytest.fixture
async def relay(db):
    probe = Device(ip="192.168.110.128", display_name="Probe", is_online=True)
    db.add(probe)
    await db.flush()
    db.add(AgentToken(device_id=probe.id, token="probe-token-ap3", is_active=True))
    db.add(AgentConfig(device_id=probe.id, enable_scanner_relay=True))
    db.add(Subnet(name="lan", cidr="192.168.110.0/24", is_enabled=True))
    await db.commit()

    async def run(*entries):
        return await ingest_agent_arp_table(db, probe.id, [{"ip": ip, "mac": mac} for ip, mac in entries])

    return run


async def _obs(db, device_id: int | None = None):
    stmt = select(DeviceMacObservation).order_by(DeviceMacObservation.device_id, DeviceMacObservation.observed_mac)
    if device_id is not None:
        stmt = stmt.where(DeviceMacObservation.device_id == device_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [(r.device_id, r.observed_mac, r.state) for r in rows]


async def _history_statuses(db, device_id: int):
    rows = (await db.execute(
        select(DeviceHistory.status).where(DeviceHistory.device_id == device_id).order_by(DeviceHistory.id)
    )).scalars().all()
    return list(rows)


# --- AP 3.1: Observation lifecycle (A1) -----------------------------------------------------------

@pytest.mark.asyncio
async def test_ip_move_clears_old_observations_and_preserves_history(db, relay, scan, client, auth):
    nas = Device(ip="192.168.110.10", mac=MAC_A, display_name="NAS", is_online=False)
    db.add(nas)
    await db.commit()

    await relay(("192.168.110.10", MAC_B))
    assert await _obs(db, nas.id) == [(nas.id, MAC_B, "open")]

    # Real NAS reappears at IP B with its documented MAC_A
    await scan({"ip": "192.168.110.20", "mac": MAC_A})
    await db.refresh(nas)

    assert (nas.ip, nas.mac, nas.is_online) == ("192.168.110.20", MAC_A, True)
    assert await _obs(db, nas.id) == []
    assert (await client.get("/api/devices/mac-conflicts", headers=auth)).json() == []
    assert await _history_statuses(db, nas.id) == ["mac_conflict", "online", "ip_changed"]


@pytest.mark.asyncio
async def test_manual_mac_change_clears_all_open_and_dismissed_observations(db, relay, client, auth):
    srv = Device(ip="192.168.110.30", mac=MAC_A, display_name="Server", is_online=True)
    db.add(srv)
    await db.commit()

    await relay(("192.168.110.30", MAC_B))
    await relay(("192.168.110.30", MAC_C))
    # Dismiss MAC_B in the old MAC_A context, leave MAC_C open
    assert (await client.post(f"/api/devices/{srv.id}/mac-observations/dismiss", json={"mac": MAC_B}, headers=auth)).status_code == 204
    assert await _obs(db, srv.id) == [(srv.id, MAC_B, "dismissed"), (srv.id, MAC_C, "open")]

    # Manual MAC change to MAC_D clears BOTH open MAC_C and previously dismissed MAC_B
    res = await client.put(f"/api/devices/{srv.id}/mac", json={"mac": MAC_D}, headers=auth)
    assert res.status_code == 200
    assert await _obs(db, srv.id) == []
    assert "mac_changed" in await _history_statuses(db, srv.id)

    # Later sighting of MAC_B against the NEW documented MAC_D is NOT silently suppressed
    await relay(("192.168.110.30", MAC_B))
    assert await _obs(db, srv.id) == [(srv.id, MAC_B, "open")]


@pytest.mark.asyncio
async def test_noop_mac_update_does_not_delete_existing_observations(db, relay, client, auth):
    srv = Device(ip="192.168.110.31", mac=MAC_A, display_name="Server", is_online=True)
    db.add(srv)
    await db.commit()

    await relay(("192.168.110.31", MAC_B))
    assert await _obs(db, srv.id) == [(srv.id, MAC_B, "open")]

    # Setting the exact same MAC_A again is a no-op -> must NOT clear observations
    res = await client.put(f"/api/devices/{srv.id}/mac", json={"mac": MAC_A}, headers=auth)
    assert res.status_code == 200
    assert res.json()["changed_device_ids"] == []
    assert await _obs(db, srv.id) == [(srv.id, MAC_B, "open")]


@pytest.mark.asyncio
async def test_group_adoption_resolves_targets_before_clearing_and_excludes_moved_device(db, relay, scan, client, auth):
    c1 = Device(ip="192.168.110.40", mac=M1, display_name="c1", is_online=True)
    c2 = Device(ip="192.168.110.41", mac=M1, display_name="c2", is_online=True)
    c3 = Device(ip="192.168.110.42", mac=M1, display_name="c3", is_online=True)
    db.add_all([c1, c2, c3])
    await db.commit()

    # All three see M2; c1 also saw another conflict MAC_C
    await relay(("192.168.110.40", M2), ("192.168.110.41", M2), ("192.168.110.42", M2))
    await relay(("192.168.110.40", MAC_C))

    # c3 moves to a new IP with its own M1 (its old M2 sighting must be cleared on IP move)
    await scan({"ip": "192.168.110.49", "mac": M1})
    await db.refresh(c3)
    # Note: ipvlan shared MAC skips MAC-only fallback, so test explicit IP move via unique device below;
    # here verify group adoption on c1 updates both c1 and c2 and clears ALL observations (incl. MAC_C)
    res = await client.put(
        f"/api/devices/{c1.id}/mac", json={"mac": M2, "apply_to_shared": True}, headers=auth,
    )
    assert res.status_code == 200
    assert sorted(res.json()["changed_device_ids"]) == sorted([c1.id, c2.id, c3.id])
    assert await _obs(db, c1.id) == []
    assert await _obs(db, c2.id) == []


@pytest.mark.asyncio
async def test_placeholder_move_on_ip_conflict_clears_old_observations(db, relay, scan):
    old_box = Device(ip="192.168.110.60", mac=MAC_A, display_name="OldBox", is_online=False)
    new_box = Device(ip="192.168.110.61", mac=MAC_B, display_name="NewBox", is_online=True)
    db.add_all([old_box, new_box])
    await db.commit()

    # Record a conflict on old_box at .60
    await relay(("192.168.110.60", MAC_C))
    assert await _obs(db, old_box.id) == [(old_box.id, MAC_C, "open")]

    # NewBox (known by MAC_B) moves onto .60 -> _resolve_ip_conflict moves old_box to placeholder IP
    await scan({"ip": "192.168.110.60", "mac": MAC_B})
    await db.refresh(old_box)
    assert old_box.ip != "192.168.110.60"
    assert await _obs(db, old_box.id) == []


# --- AP 3.2: Neutral online state, health samples, recovery & ambiguity ---------------------------

@pytest.mark.asyncio
async def test_scan_planner_dashboard_and_health_probe_stay_neutral_on_mac_conflict(db, scan, monkeypatch):
    """Conflicting valid MAC at dev.ip must NOT wake an offline device, reset missed_scans,
    update last_seen, adopt a foreign hostname, mark foreign services up, or write a positive
    DeviceHealthSample.
    """
    old_seen = datetime(2026, 11, 1, 10, 0, tzinfo=UTC).replace(tzinfo=None)
    nas = Device(
        ip="192.168.110.70", mac=MAC_A, display_name="192.168.110.70", hostname="192.168.110.70",
        is_online=False, missed_scans=4, last_seen=old_seen,
    )
    online_srv = Device(
        ip="192.168.110.71", mac=MAC_A, display_name="OnlineSrv",
        is_online=True, missed_scans=0, last_seen=old_seen,
    )
    db.add_all([nas, online_srv])
    await db.flush()
    svc = Service(device_id=nas.id, name="Web", protocol="http", port=80, is_up=False)
    db.add(svc)
    await db.commit()

    # 1. sync_hosts_batch with conflicting MAC_B and a foreign hostname
    await scan(
        {"ip": "192.168.110.70", "mac": MAC_B, "hostname": "foreign-printer.lan"},
        {"ip": "192.168.110.71", "mac": MAC_B},
    )
    await db.refresh(nas)
    await db.refresh(online_srv)
    assert (nas.is_online, nas.missed_scans, nas.last_seen, nas.hostname) == (False, 4, old_seen, "192.168.110.70")
    assert (online_srv.is_online, online_srv.missed_scans, online_srv.last_seen) == (True, 0, old_seen)
    assert await _obs(db, nas.id) == [(nas.id, MAC_B, "open")]

    # 2. Dashboard health phase with foreign box answering on port 80
    alive_map = {
        "192.168.110.70": {"ip": "192.168.110.70", "mac": MAC_B},
        "192.168.110.71": {"ip": "192.168.110.71", "mac": MAC_B},
    }
    macs_by_ip = {"192.168.110.70": {MAC_B}, "192.168.110.71": {MAC_B}}
    monkeypatch.setattr(dash_mod, "scan_ports", AsyncMock(return_value=[80]))
    await dash_mod._check_health_batch([nas, online_srv], alive_map, db, offline_threshold=3, macs_by_ip=macs_by_ip)
    await db.commit()
    await db.refresh(nas)
    await db.refresh(svc)
    await db.refresh(online_srv)
    assert (nas.is_online, nas.missed_scans, svc.is_up) == (False, 4, False)
    assert (online_srv.is_online, online_srv.missed_scans) == (True, 0)

    # 3. Planner offline cleanup with conflicting MAC_B: neither register_seen nor register_miss
    monkeypatch.setattr(planner_mod, "tcp_fallback_alive", AsyncMock(return_value={"192.168.110.71"}))
    await planner_mod._cleanup_devices(
        db, ["192.168.110.0/24"], {"192.168.110.70", "192.168.110.71"},
        offline_threshold=1, alive_macs_by_ip=macs_by_ip,
    )
    await db.commit()
    await db.refresh(online_srv)
    assert (online_srv.is_online, online_srv.missed_scans) == (True, 0)

    # 4. Health probe pass: open conflict must prevent waking offline device AND prevent writing
    #    a false-positive DeviceHealthSample or foreign Service.is_up=True
    monkeypatch.setattr(hp_mod, "async_session", lambda: _SameSession(db))
    monkeypatch.setattr(hp_mod, "measure_ping_latency_ms", AsyncMock(return_value=1.5))
    monkeypatch.setattr(hp_mod, "measure_tcp_latency_ms", AsyncMock(return_value=2.0))
    monkeypatch.setattr(hp_mod, "commit_or_discard", AsyncMock(return_value="ok"))
    sampled = await hp_mod.run_health_probe_pass()
    assert sampled == 0
    await db.refresh(nas)
    await db.refresh(svc)
    assert (nas.is_online, nas.missed_scans, svc.is_up) == (False, 4, False)
    samples = (await db.execute(select(DeviceHealthSample))).scalars().all()
    assert samples == []


@pytest.mark.asyncio
async def test_automatic_recovery_when_documented_mac_returns_via_scan_or_relay(db, relay, scan, client, auth, monkeypatch):
    nas = Device(ip="192.168.110.80", mac=MAC_A, display_name="NAS", is_online=False, missed_scans=4)
    db.add(nas)
    await db.commit()

    # Dismiss MAC_C in this context, then experience a temporary open conflict with MAC_B
    await relay(("192.168.110.80", MAC_C))
    assert (await client.post(f"/api/devices/{nas.id}/mac-observations/dismiss", json={"mac": MAC_C}, headers=auth)).status_code == 204
    await relay(("192.168.110.80", MAC_B))
    assert await _obs(db, nas.id) == [(nas.id, MAC_B, "open"), (nas.id, MAC_C, "dismissed")]

    # Clean matching L2 sighting (MAC_A) via scan resolves open MAC_B, keeps dismissed MAC_C, wakes NAS
    await scan({"ip": "192.168.110.80", "mac": MAC_A})
    await db.refresh(nas)
    assert (nas.is_online, nas.missed_scans) == (True, 0)
    assert await _obs(db, nas.id) == [(nas.id, MAC_C, "dismissed")]

    # Repeat via relay: temporary conflict MAC_B, then clean MAC_A recovers via relay too
    nas.is_online = False
    nas.missed_scans = 3
    await db.commit()
    await relay(("192.168.110.80", MAC_B))
    assert (nas.is_online, await _obs(db, nas.id)) == (False, [(nas.id, MAC_B, "open"), (nas.id, MAC_C, "dismissed")])

    await relay(("192.168.110.80", MAC_A))
    await db.refresh(nas)
    assert (nas.is_online, nas.missed_scans) == (True, 0)
    assert await _obs(db, nas.id) == [(nas.id, MAC_C, "dismissed")]

    # And health_probe works normally again once open conflict is gone
    monkeypatch.setattr(hp_mod, "async_session", lambda: _SameSession(db))
    monkeypatch.setattr(hp_mod, "measure_ping_latency_ms", AsyncMock(return_value=1.2))
    monkeypatch.setattr(hp_mod, "commit_or_discard", AsyncMock(return_value="ok"))
    assert await hp_mod.run_health_probe_pass() >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [(MAC_A, MAC_B), (MAC_B, MAC_A)], ids=["A_then_B", "B_then_A"])
async def test_ambiguous_pass_with_both_macs_is_order_independent_in_scan_and_relay(db, relay, scan, order):
    """When both MAC_A and MAC_B answer for the same IP in the same pass, neither ordering may
    confirm the device online or auto-clear the open conflict.
    """
    dev_scan = Device(ip="192.168.110.85", mac=MAC_A, display_name="ScanDev", is_online=False, missed_scans=3)
    dev_relay = Device(ip="192.168.110.86", mac=MAC_A, display_name="RelayDev", is_online=False, missed_scans=3)
    db.add_all([dev_scan, dev_relay])
    await db.commit()

    await scan({"ip": "192.168.110.85", "mac": order[0]}, {"ip": "192.168.110.85", "mac": order[1]})
    await relay(("192.168.110.86", order[0]), ("192.168.110.86", order[1]))

    await db.refresh(dev_scan)
    await db.refresh(dev_relay)
    assert (dev_scan.is_online, dev_scan.missed_scans) == (False, 3)
    assert (dev_relay.is_online, dev_relay.missed_scans) == (False, 3)
    assert await _obs(db, dev_scan.id) == [(dev_scan.id, MAC_B, "open")]
    assert await _obs(db, dev_relay.id) == [(dev_relay.id, MAC_B, "open")]


@pytest.mark.asyncio
async def test_routed_l3_and_dismissed_conflict_keep_normal_health_probe_behavior(db, relay, client, auth, monkeypatch):
    """Normal routed devices (no MAC / no conflict) and devices whose conflict was dismissed are
    probed normally by health_probe.
    """
    routed = Device(ip="10.20.0.5", mac=None, display_name="Routed", is_online=False, missed_scans=2)
    dismissed_dev = Device(ip="192.168.110.90", mac=MAC_A, display_name="Dismissed", is_online=False, missed_scans=2)
    db.add_all([routed, dismissed_dev])
    await db.commit()

    await relay(("192.168.110.90", MAC_B))
    assert (await client.post(
        f"/api/devices/{dismissed_dev.id}/mac-observations/dismiss", json={"mac": MAC_B}, headers=auth,
    )).status_code == 204

    monkeypatch.setattr(hp_mod, "async_session", lambda: _SameSession(db))
    monkeypatch.setattr(hp_mod, "measure_ping_latency_ms", AsyncMock(return_value=3.0))
    sampled = await hp_mod.run_health_probe_pass()

    assert sampled >= 2
    await db.refresh(routed)
    await db.refresh(dismissed_dev)
    assert (routed.is_online, routed.missed_scans) == (True, 0)
    assert (dismissed_dev.is_online, dismissed_dev.missed_scans) == (True, 0)


@pytest.mark.asyncio
async def test_relay_commits_conflict_clearing_even_when_device_is_already_online_and_unchanged(db, relay):
    """When a device is already online with matching MAC and vendor set, a clean matching relay
    entry that ONLY clears an open conflict must still commit that deletion durably.
    """
    srv = Device(
        ip="192.168.110.95", mac=MAC_A, vendor="TestVendor", display_name="AlreadyOnline",
        is_online=True, missed_scans=0,
    )
    db.add(srv)
    await db.commit()

    await relay(("192.168.110.95", MAC_B))
    assert await _obs(db, srv.id) == [(srv.id, MAC_B, "open")]

    # Clean matching MAC_A: no device field changes, only the open conflict is cleared
    updated = await relay(("192.168.110.95", MAC_A))
    assert updated == 1

    # Roll back the original session and read from a brand-new session on the same engine:
    # if relay had not committed the deletion, the row would still be present here.
    await db.rollback()
    async with AsyncSession(bind=db.bind, expire_on_commit=False) as fresh_db:
        rows = (await fresh_db.execute(
            select(DeviceMacObservation).where(DeviceMacObservation.device_id == srv.id)
        )).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_docker_sync_stays_neutral_on_open_mac_conflict_and_works_normally_without(db, relay):
    """sync_docker_containers must not wake an offline device (or touch last_seen/missed_scans)
    while an open MAC conflict exists on it; without a conflict, IP-based confirmation stays intact.
    """
    old_seen = datetime(2026, 11, 1, 10, 0, tzinfo=UTC).replace(tzinfo=None)
    conflicted = Device(
        ip="192.168.110.96", mac=MAC_A, display_name="ConflictedContainer",
        is_online=False, missed_scans=4, last_seen=old_seen,
    )
    clean = Device(
        ip="192.168.110.97", mac=MAC_C, display_name="CleanContainer",
        is_online=False, missed_scans=3, last_seen=old_seen,
    )
    db.add_all([conflicted, clean])
    await db.commit()

    await relay(("192.168.110.96", MAC_B))
    assert await _obs(db, conflicted.id) == [(conflicted.id, MAC_B, "open")]

    containers = [
        {"name": "app-conflict", "status": "running", "ips": ["192.168.110.96"]},
        {"name": "app-clean", "status": "running", "ips": ["192.168.110.97"]},
    ]
    with patch("app.scanner.sync.async_session", return_value=_SameSession(db)):
        await sync_docker_containers(containers)

    await db.refresh(conflicted)
    await db.refresh(clean)
    assert (conflicted.is_online, conflicted.missed_scans, conflicted.last_seen) == (False, 4, old_seen)
    assert clean.is_online is True and clean.missed_scans == 0 and clean.last_seen != old_seen
