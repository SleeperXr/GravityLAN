"""Tests for Phase 3: Events, Notifications, and History read state."""

import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from app.models.device import Device, DeviceHistory, DiscoveredHost
from app.models.setting import Setting
from app.scanner.sync import sync_hosts_batch


class DBSessionContextMock:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_three_scans_send_exactly_one_notification(db):
    """Acceptance criterion: A new device seen by three scans triggers exactly one notification."""
    # Ensure initial scan is completed so notifications are active
    db.add(Setting(key="scanner.initial_scan_done", value="true", category="scan"))
    await db.commit()

    captured_events = []

    async def mock_trigger(event_type, data):
        captured_events.append((event_type, data))

    new_host = {
        "ip": "192.168.1.200",
        "mac": "aa:bb:cc:dd:ee:99",
        "hostname": "new-printer.lan",
        "vendor": "HP",
    }

    session_ctx = DBSessionContextMock(db)
    with patch("app.scanner.sync.async_session", return_value=session_ctx), \
         patch("app.services.webhook_service.trigger_webhooks", side_effect=mock_trigger):

        # Scan 1: Discovers the new host for the first time
        await sync_hosts_batch([new_host], is_planner_scan=True)
        assert len(captured_events) == 1
        assert captured_events[0][0] == "new_device"
        assert captured_events[0][1]["ip"] == "192.168.1.200"

        # Scan 2: Host is seen again
        await sync_hosts_batch([new_host], is_planner_scan=True)
        assert len(captured_events) == 1, "Second scan must not trigger duplicate notification"

        # Scan 3: Host is seen a third time
        await sync_hosts_batch([new_host], is_planner_scan=True)
        assert len(captured_events) == 1, "Third scan must not trigger duplicate notification"


@pytest.mark.asyncio
async def test_initial_inventory_suppresses_new_device_events(db):
    """During initial inventory (first pass before initial_scan_done is recorded), no new_device alerts are emitted."""
    # Initial scan done is NOT set, and setup.complete is NOT set
    captured_events = []

    async def mock_trigger(event_type, data):
        captured_events.append((event_type, data))

    hosts = [
        {"ip": "192.168.1.10", "mac": "aa:bb:cc:00:00:10", "hostname": "host1.lan"},
        {"ip": "192.168.1.11", "mac": "aa:bb:cc:00:00:11", "hostname": "host2.lan"},
    ]

    session_ctx = DBSessionContextMock(db)
    with patch("app.scanner.sync.async_session", return_value=session_ctx), \
         patch("app.services.webhook_service.trigger_webhooks", side_effect=mock_trigger):
        # Scan during initial inventory
        await sync_hosts_batch(hosts, is_planner_scan=True)
        assert len(captured_events) == 0, "No alerts during initial inventory"

    # Now initial inventory pass finishes
    db.add(Setting(key="scanner.initial_scan_done", value="true", category="scan"))
    await db.commit()

    # Next scan finds a brand new device
    brand_new = {"ip": "192.168.1.12", "mac": "aa:bb:cc:00:00:12", "hostname": "host3.lan"}
    with patch("app.scanner.sync.async_session", return_value=session_ctx), \
         patch("app.services.webhook_service.trigger_webhooks", side_effect=mock_trigger):
        await sync_hosts_batch([brand_new], is_planner_scan=True)
        assert len(captured_events) == 1
        assert captured_events[0][0] == "new_device"
        assert captured_events[0][1]["ip"] == "192.168.1.12"


@pytest.mark.asyncio
async def test_verified_ip_change_emits_ip_changed_event(db):
    """When a dashboard device's IP change is verified by MAC, it records status='ip_changed' and triggers a webhook."""
    # Create an initial dashboard device
    dev = Device(
        ip="192.168.1.50",
        mac="aa:bb:cc:55:66:77",
        display_name="Workstation",
        device_type="computer",
        device_subtype="PC",
        is_online=True,
    )
    db.add(dev)
    await db.commit()
    await db.refresh(dev)

    captured_events = []

    async def mock_trigger(event_type, data):
        captured_events.append((event_type, data))

    session_ctx = DBSessionContextMock(db)
    # Scanner sees device at new IP with same verified MAC
    with patch("app.scanner.sync.async_session", return_value=session_ctx), \
         patch("app.services.webhook_service.trigger_webhooks", side_effect=mock_trigger):
        await sync_hosts_batch(
            [{"ip": "192.168.1.60", "mac": "aa:bb:cc:55:66:77", "hostname": "workstation.lan"}],
            is_planner_scan=True,
        )

    await db.refresh(dev)
    assert dev.ip == "192.168.1.60"
    assert dev.old_ip == "192.168.1.50"

    # Verify history entry
    res = await db.execute(select(DeviceHistory).where(DeviceHistory.device_id == dev.id))
    histories = res.scalars().all()
    ip_events = [h for h in histories if h.status == "ip_changed"]
    assert len(ip_events) == 1
    assert "IP changed from 192.168.1.50 to 192.168.1.60" in ip_events[0].message
    assert ip_events[0].read is False

    # Verify webhook
    assert len(captured_events) == 1
    assert captured_events[0][0] == "device.ip_changed"
    assert captured_events[0][1]["device_id"] == dev.id
    assert captured_events[0][1]["old_ip"] == "192.168.1.50"
    assert captured_events[0][1]["new_ip"] == "192.168.1.60"


@pytest.mark.asyncio
async def test_notifications_read_endpoints(client, admin_token, db):
    """Test reading notifications and marking them as read."""
    dev = Device(
        ip="192.168.1.70",
        display_name="NAS",
        device_type="nas",
        device_subtype="Storage",
        is_online=True,
    )
    db.add(dev)
    await db.commit()
    await db.refresh(dev)

    h1 = DeviceHistory(device_id=dev.id, status="ip_changed", message="IP changed to 192.168.1.70", read=False)
    h2 = DeviceHistory(device_id=dev.id, status="new_device", message="Device added to dashboard", read=False)
    db.add_all([h1, h2])
    await db.commit()
    await db.refresh(h1)
    await db.refresh(h2)

    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Fetch unread
    res = await client.get("/api/notifications?unread=true", headers=headers)
    assert res.status_code == 200
    items = res.json()
    ids = {item["id"] for item in items}
    assert h1.id in ids and h2.id in ids

    # 2. Mark h1 as read
    res_read1 = await client.post(f"/api/notifications/{h1.id}/read", headers=headers)
    assert res_read1.status_code == 200
    assert res_read1.json()["read"] is True

    # Check unread filter
    res_unread = await client.get("/api/notifications?unread=true", headers=headers)
    unread_ids = {item["id"] for item in res_unread.json()}
    assert h1.id not in unread_ids
    assert h2.id in unread_ids

    # Check read filter
    res_read = await client.get("/api/notifications?unread=false", headers=headers)
    read_ids = {item["id"] for item in res_read.json()}
    assert h1.id in read_ids

    # 3. Mark all as read
    res_all = await client.post("/api/notifications/read-all", headers=headers)
    assert res_all.status_code == 200
    assert res_all.json()["marked_read"] >= 1

    # Unread list is now empty
    res_unread_now = await client.get(f"/api/notifications?unread=true&device_id={dev.id}", headers=headers)
    assert len(res_unread_now.json()) == 0


@pytest.mark.asyncio
async def test_add_device_from_ip_records_new_device_history(client, admin_token, db):
    """Adding a device via /api/devices/add-from-ip creates a history entry with status='new_device'."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    with patch("app.scanner.hostname.resolve_hostname", return_value="nas-device.lan"), \
         patch("app.scanner.arp.resolve_mac_addresses", side_effect=lambda hosts: hosts):
        res = await client.post("/api/devices/add-from-ip?ip=192.168.1.85", headers=headers)
    assert res.status_code == 200
    dev_id = res.json()["id"]

    res_hist = await client.get(f"/api/devices/{dev_id}/history", headers=headers)
    assert res_hist.status_code == 200
    history = res_hist.json()
    assert len(history) >= 1
    new_dev_entries = [h for h in history if h["status"] == "new_device"]
    assert len(new_dev_entries) == 1
    assert new_dev_entries[0]["read"] is False

    # Mark device history as read via device endpoint
    res_mark = await client.post(f"/api/devices/{dev_id}/history/read-all", headers=headers)
    assert res_mark.status_code == 200
    assert res_mark.json()["marked_read"] >= 1


@pytest.mark.asyncio
async def test_new_device_is_announced_only_after_the_commit(db):
    """A rolled back batch announces nothing, so the next scan's notification is the only one."""
    from sqlalchemy.orm.exc import StaleDataError

    db.add(Setting(key="scanner.initial_scan_done", value="true", category="scan"))
    await db.commit()

    captured_events = []

    async def mock_trigger(event_type, data):
        captured_events.append(event_type)

    host = {"ip": "192.168.1.201", "mac": "aa:bb:cc:dd:ee:98", "hostname": "cam.lan", "vendor": None}
    with patch("app.scanner.sync.async_session", return_value=DBSessionContextMock(db)), \
         patch("app.services.webhook_service.trigger_webhooks", side_effect=mock_trigger):
        with patch.object(db, "commit", AsyncMock(side_effect=StaleDataError())):
            await sync_hosts_batch([host], is_planner_scan=True)
        assert captured_events == []

        await sync_hosts_batch([host], is_planner_scan=True)
        assert captured_events == ["new_device"]
