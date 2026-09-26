import pytest
from unittest.mock import patch
from datetime import datetime, timezone
from sqlalchemy import select
from app.models.device import Device, DiscoveredHost, DeviceHistory
from app.scanner.sync import sync_hosts_batch
from app.database.migrations import _clean_corrupted_ip_placeholders

class DBSessionContextMock:
    def __init__(self, db):
        self.db = db
    async def __aenter__(self):
        return self.db
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_ipvlan_shared_mac_matching(db):
    """
    Test scenario:
    1. Unraid Host and a Docker container share the same host MAC address ('02:42:ac:11:00:01').
    2. Host has IP '192.168.1.10', Container has IP '192.168.1.50'.
    3. Scanning '192.168.1.50' with MAC '02:42:ac:11:00:01' must match the Container device,
       NOT the Host device.
    """
    host_dev = Device(
        ip="192.168.1.10",
        mac="02:42:ac:11:00:01",
        display_name="Unraid Host",
        is_online=True
    )
    container_dev = Device(
        ip="192.168.1.50",
        mac="02:42:ac:11:00:01",
        display_name="Nextcloud Container",
        is_online=True
    )
    db.add_all([host_dev, container_dev])
    await db.commit()

    scan_hosts = [{
        "ip": "192.168.1.50",
        "mac": "02:42:ac:11:00:01",
        "hostname": "nextcloud"
    }]

    session_ctx = DBSessionContextMock(db)
    with patch("app.scanner.sync.async_session", return_value=session_ctx):
        await sync_hosts_batch(scan_hosts, is_planner_scan=True)

    res_host = await db.execute(select(Device).where(Device.ip == "192.168.1.10"))
    h = res_host.scalar_one()
    assert h.display_name == "Unraid Host"
    assert h.ip == "192.168.1.10"

    res_container = await db.execute(select(Device).where(Device.ip == "192.168.1.50"))
    c = res_container.scalar_one()
    assert c.display_name == "Nextcloud Container"
    assert c.ip == "192.168.1.50"


@pytest.mark.asyncio
async def test_ip_conflict_sets_placeholder_without_offline_prefix(db):
    """
    Test scenario:
    1. Device A has MAC A and IP '192.168.1.100'.
    2. Device B has MAC B and IP '192.168.1.200'.
    3. Scan finds MAC A at '192.168.1.200'.
    4. Device A gets '192.168.1.200'. Device B gets an available valid IP (e.g. old_ip or 0.0.0.x)
       with ip_placeholder=True and is_online=False. IP must NEVER start with 'offline-'.
    """
    dev_a = Device(
        ip="192.168.1.100",
        mac="00:11:22:33:44:aa",
        display_name="Device A",
        is_online=True
    )
    dev_b = Device(
        ip="192.168.1.200",
        mac="00:11:22:33:44:bb",
        display_name="Device B",
        is_online=True
    )
    db.add_all([dev_a, dev_b])
    await db.commit()

    scan_hosts = [{
        "ip": "192.168.1.200",
        "mac": "00:11:22:33:44:aa"
    }]

    session_ctx = DBSessionContextMock(db)
    with patch("app.scanner.sync.async_session", return_value=session_ctx):
        await sync_hosts_batch(scan_hosts, is_planner_scan=True)

    res_a = await db.execute(select(Device).where(Device.mac == "00:11:22:33:44:aa"))
    a = res_a.scalar_one()
    assert a.ip == "192.168.1.200"

    res_b = await db.execute(select(Device).where(Device.mac == "00:11:22:33:44:bb"))
    b = res_b.scalar_one()
    assert not b.ip.startswith("offline-")
    assert b.ip_placeholder is True
    assert b.is_online is False


@pytest.mark.asyncio
async def test_unverified_match_no_ip_changed_notification(db):
    """
    Test scenario:
    1. Device is matched via Hostname (unverified match).
    2. IP changes during sync.
    3. Device IP is updated, but NO DeviceHistory "IP changed" entry is created.
    """
    dev = Device(
        ip="10.0.0.5",
        mac="00:00:00:00:00:00",  # invalid MAC
        hostname="unverified-host",
        display_name="Unverified Device",
        is_online=True
    )
    db.add(dev)
    await db.commit()

    scan_hosts = [{
        "ip": "10.0.0.99",
        "mac": None,
        "hostname": "unverified-host"
    }]

    session_ctx = DBSessionContextMock(db)
    with patch("app.scanner.sync.async_session", return_value=session_ctx):
        await sync_hosts_batch(scan_hosts, is_planner_scan=True)

    res = await db.execute(select(Device).where(Device.hostname == "unverified-host"))
    updated_dev = res.scalar_one()
    assert updated_dev.ip == "10.0.0.99"

    # Check DeviceHistory
    res_hist = await db.execute(select(DeviceHistory).where(DeviceHistory.device_id == updated_dev.id))
    histories = res_hist.scalars().all()
    assert len(histories) == 0, "No DeviceHistory IP changed notification should be emitted for unverified match"


@pytest.mark.asyncio
async def test_migration_cleans_offline_mac_ips(db):
    """
    Test scenario:
    1. Database contains a Device with ip='offline-02:63:aa:bb:cc:dd'.
    2. Running _clean_corrupted_ip_placeholders repairs the IP to a valid string and sets ip_placeholder=True.
    """
    corrupted_dev = Device(
        ip="offline-02:63:aa:bb:cc:dd",
        mac="02:63:aa:bb:cc:dd",
        display_name="Corrupted Container",
        is_online=False,
        old_ip="192.168.1.150"
    )
    db.add(corrupted_dev)
    await db.commit()

    await _clean_corrupted_ip_placeholders(db)
    await db.commit()

    res = await db.execute(select(Device).where(Device.id == corrupted_dev.id))
    repaired = res.scalar_one()
    assert not repaired.ip.startswith("offline-")
    assert repaired.ip == "192.168.1.150"
    assert repaired.ip_placeholder is True
    assert repaired.is_online is False


@pytest.mark.asyncio
async def test_migration_cleans_multiple_corrupted_devices(db):
    """
    Test scenario:
    Multiple devices in DB have 'offline-<MAC>' IPs. Migration must assign UNIQUE valid IPs to each
    and commit without UNIQUE constraint errors.
    """
    devices = [
        Device(ip=f"offline-mac-{i}", mac=f"02:00:00:00:00:0{i}", display_name=f"Corrupted {i}", is_online=False)
        for i in range(8)
    ]
    db.add_all(devices)
    await db.commit()

    await _clean_corrupted_ip_placeholders(db)
    await db.commit()

    res = await db.execute(select(Device).where(Device.ip_placeholder == True))
    repaired_devs = res.scalars().all()
    assert len(repaired_devs) >= 8
    assigned_ips = [d.ip for d in repaired_devs]
    assert len(assigned_ips) == len(set(assigned_ips)), "All repaired IPs must be strictly unique"
    for ip in assigned_ips:
        assert not ip.startswith("offline-")


@pytest.mark.asyncio
async def test_docker_sync_restores_placeholder_ip_by_container_name(db):
    """
    Test scenario:
    1. Device 'Lancache' currently has placeholder IP '0.0.0.1' and ip_placeholder=True.
    2. Docker sync runs with container name 'Lancache' running at IP '192.168.100.15'.
    3. Result: 'Lancache' device IP is restored to '192.168.100.15', ip_placeholder is set False, and device is set ONLINE.
    """
    from app.scanner.sync import sync_docker_containers

    dev = Device(
        ip="0.0.0.1",
        mac="02:63:aa:bb:cc:dd",
        display_name="Lancache",
        ip_placeholder=True,
        is_online=False
    )
    db.add(dev)
    await db.commit()

    containers = [{
        "id": "c1",
        "name": "Lancache",
        "ips": ["192.168.100.15"],
        "status": "running"
    }]

    session_ctx = DBSessionContextMock(db)
    with patch("app.scanner.sync.async_session", return_value=session_ctx):
        await sync_docker_containers(containers)

    res = await db.execute(select(Device).where(Device.display_name == "Lancache"))
    updated = res.scalar_one()
    assert updated.ip == "192.168.100.15"
    assert updated.ip_placeholder is False
    assert updated.is_online is True




@pytest.mark.asyncio
async def test_ip_match_survives_mac_shared_by_several_records(db, caplog):
    """
    Regression: 'Multiple rows were found when one or none was required'.
    1. Unraid host and an ipvlan container share MAC M (two Devices, two DiscoveredHosts).
    2. Another device sits at '192.168.1.60' with its own (older) MAC.
    3. A scan reports '192.168.1.60' with MAC M. Looking up "the" owner of M used to
       raise, so the host was skipped on every scan. With several owners the MAC can't
       identify anyone (ipvlan), so the IP match must be kept.
    """
    shared_mac = "02:42:ac:11:00:01"
    db.add_all([
        Device(ip="192.168.1.10", mac=shared_mac, display_name="Unraid Host", is_online=True),
        Device(ip="192.168.1.50", mac=shared_mac, display_name="Nextcloud Container", is_online=True),
        Device(ip="192.168.1.60", mac="02:42:ac:11:00:99", display_name="Paperless Container", is_online=True),
        DiscoveredHost(ip="192.168.1.10", mac=shared_mac, hostname="unraid"),
        DiscoveredHost(ip="192.168.1.50", mac=shared_mac, hostname="nextcloud"),
        DiscoveredHost(ip="192.168.1.60", mac="02:42:ac:11:00:99", hostname="paperless"),
    ])
    await db.commit()

    scan_hosts = [{"ip": "192.168.1.60", "mac": shared_mac, "hostname": "paperless"}]

    session_ctx = DBSessionContextMock(db)
    with patch("app.scanner.sync.async_session", return_value=session_ctx):
        results = await sync_hosts_batch(scan_hosts, is_planner_scan=True)

    assert "Failed to process host" not in caplog.text
    assert len(results) == 1

    res = await db.execute(select(Device).where(Device.ip == "192.168.1.60"))
    assert res.scalar_one().display_name == "Paperless Container"
    res = await db.execute(select(Device).where(Device.ip == "192.168.1.10"))
    assert res.scalar_one().display_name == "Unraid Host"
    res = await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == "192.168.1.60"))
    assert res.scalar_one().hostname == "paperless"
