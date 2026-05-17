import pytest
from unittest.mock import patch
from datetime import datetime, timezone
from app.models.device import Device, DiscoveredHost, DeviceHistory
from app.scanner.sync import sync_hosts_batch

class DBSessionContextMock:
    def __init__(self, db):
        self.db = db
    async def __aenter__(self):
        return self.db
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

@pytest.mark.asyncio
async def test_device_matching_mac_ip_change(db):
    """
    Test scenario:
    1. Existing device has MAC '00:11:22:33:44:55' and IP '192.168.100.37'.
    2. A new scan finds MAC '00:11:22:33:44:55' at a new IP '192.168.100.46'.
    3. Result: The existing device is updated with the new IP immediately (bypassing staleness),
       and no duplicate Device or DiscoveredHost is created.
    """
    # 1. Arrange
    dev = Device(
        ip="192.168.100.37",
        mac="00:11:22:33:44:55",
        display_name="Test Device",
        is_online=True,
        last_seen=datetime.now(timezone.utc)
    )
    disc = DiscoveredHost(
        ip="192.168.100.37",
        mac="00:11:22:33:44:55",
        custom_name="Test Device",
        is_online=True,
        is_monitored=True,
        last_seen=datetime.now(timezone.utc)
    )
    db.add(dev)
    db.add(disc)
    await db.commit()

    scan_hosts = [{
        "ip": "192.168.100.46",
        "mac": "00:11:22:33:44:55",
        "hostname": "test-host",
        "vendor": "TestVendor"
    }]

    # 2. Act
    session_ctx = DBSessionContextMock(db)
    with patch("app.scanner.sync.async_session", return_value=session_ctx):
        await sync_hosts_batch(scan_hosts, is_planner_scan=True)
    
    # 3. Assert
    from sqlalchemy import select
    res_dev = await db.execute(select(Device).where(Device.mac == "00:11:22:33:44:55"))
    devices = res_dev.scalars().all()
    
    res_disc = await db.execute(select(DiscoveredHost).where(DiscoveredHost.mac == "00:11:22:33:44:55"))
    discovered = res_disc.scalars().all()
    
    assert len(devices) == 1, "Should not create duplicate devices"
    assert devices[0].ip == "192.168.100.46", "Device IP should be updated to the new IP"
    assert devices[0].old_ip == "192.168.100.37", "Should store old IP"
    
    assert len(discovered) == 1, "Should not create duplicate discovered hosts"
    assert discovered[0].ip == "192.168.100.46", "Discovered host IP should be updated to the new IP"
    
    # Verify DeviceHistory entry
    res_hist = await db.execute(select(DeviceHistory).where(DeviceHistory.device_id == devices[0].id))
    histories = res_hist.scalars().all()
    assert len(histories) == 1
    assert "IP changed" in histories[0].message
    assert "192.168.100.37" in histories[0].message
    assert "192.168.100.46" in histories[0].message


@pytest.mark.asyncio
async def test_device_matching_ip_conflict(db):
    """
    Test scenario:
    1. Device A has MAC '00:11:22:33:44:55' and IP '192.168.100.37'.
    2. Device B has MAC '66:77:88:99:aa:bb' and IP '192.168.100.46'.
    3. A new scan finds MAC '00:11:22:33:44:55' at IP '192.168.100.46'.
    4. Result: Device A's IP is changed to '192.168.100.46', and the conflicting Device B
       is safely moved to an offline placeholder to avoid UNIQUE constraint violation.
    """
    # 1. Arrange
    dev_a = Device(
        ip="192.168.100.37",
        mac="00:11:22:33:44:55",
        display_name="Device A",
        is_online=True
    )
    dev_b = Device(
        ip="192.168.100.46",
        mac="66:77:88:99:aa:bb",
        display_name="Device B",
        is_online=True
    )
    db.add_all([dev_a, dev_b])
    await db.commit()

    scan_hosts = [{
        "ip": "192.168.100.46",
        "mac": "00:11:22:33:44:55"
    }]

    # 2. Act
    session_ctx = DBSessionContextMock(db)
    with patch("app.scanner.sync.async_session", return_value=session_ctx):
        await sync_hosts_batch(scan_hosts, is_planner_scan=True)
    
    # 3. Assert
    from sqlalchemy import select
    # Verify Device A updated to .46
    res_a = await db.execute(select(Device).where(Device.mac == "00:11:22:33:44:55"))
    a = res_a.scalar_one()
    assert a.ip == "192.168.100.46"
    
    # Verify Device B resolved conflict
    res_b = await db.execute(select(Device).where(Device.mac == "66:77:88:99:aa:bb"))
    b = res_b.scalar_one()
    assert b.ip.startswith("offline-")
    assert b.is_online is False


@pytest.mark.asyncio
async def test_device_matching_invalid_mac(db):
    """
    Test scenario:
    1. Existing device has an empty/placeholder MAC ('00:00:00:00:00:00') and IP '192.168.100.37'.
    2. A new scan finds MAC '00:00:00:00:00:00' on IP '192.168.100.46'.
    3. Result: No automatic merging/matching is performed because the MAC is invalid,
       so no IP update occurs on the existing device.
    """
    dev = Device(
        ip="192.168.100.37",
        mac="00:00:00:00:00:00",
        display_name="Invalid MAC Device",
        is_online=True,
        last_seen=datetime.now(timezone.utc)
    )
    db.add(dev)
    await db.commit()

    scan_hosts = [{
        "ip": "192.168.100.46",
        "mac": "00:00:00:00:00:00"
    }]

    session_ctx = DBSessionContextMock(db)
    with patch("app.scanner.sync.async_session", return_value=session_ctx):
        await sync_hosts_batch(scan_hosts, is_planner_scan=True)

    from sqlalchemy import select
    res_dev = await db.execute(select(Device).where(Device.mac == "00:00:00:00:00:00"))
    devices = res_dev.scalars().all()

    # The existing device should NOT have changed its IP
    assert len(devices) == 1
    assert devices[0].ip == "192.168.100.37"
