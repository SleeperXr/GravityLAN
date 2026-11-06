"""Device API: metadata and service refresh, bulk refresh, history read state and the services endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.device import Device, DeviceHistory, Service
from app.models.setting import Setting


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


async def _device(db, **fields) -> Device:
    dev = Device(ip=fields.pop("ip", "192.0.2.30"), display_name=fields.pop("display_name", "192.0.2.30"), **fields)
    db.add(dev)
    await db.commit()
    return dev


async def _services(db, device_id: int) -> dict[int, Service]:
    db.expire_all()
    rows = (await db.execute(select(Service).where(Service.device_id == device_id))).scalars().all()
    return {s.port: s for s in rows}


# --- refresh-info -------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_info_fills_hostname_mac_and_vendor(client, db, auth, monkeypatch):
    dev = await _device(db)
    db.add(Setting(key="dns.server", value="192.0.2.53", category="scan"))
    await db.commit()
    resolve = AsyncMock(return_value="nas01.lan")
    monkeypatch.setattr("app.api.devices.resolve_hostname", resolve)

    async def fake_arp(hosts):
        hosts[0]["mac"] = "aa:bb:cc:dd:ee:01"

    monkeypatch.setattr("app.scanner.arp.resolve_mac_addresses", fake_arp)
    monkeypatch.setattr("app.api.devices.get_vendor", lambda mac: "Synology")

    res = await client.post(f"/api/devices/{dev.id}/refresh-info", headers=auth)

    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["hostname"], body["display_name"], body["mac"], body["vendor"]) == ("nas01.lan", "nas01", "aa:bb:cc:dd:ee:01", "Synology")
    # A refresh the user asked for always looks again, with the configured DNS server
    assert resolve.await_args.kwargs == {"dns_server": "192.0.2.53", "use_cache": False}


@pytest.mark.asyncio
async def test_refresh_info_keeps_a_chosen_display_name(client, db, auth, monkeypatch):
    dev = await _device(db, display_name="Keller-NAS", mac="aa:bb:cc:dd:ee:02")
    monkeypatch.setattr("app.api.devices.resolve_hostname", AsyncMock(return_value="nas01.lan"))
    arp = AsyncMock()
    monkeypatch.setattr("app.scanner.arp.resolve_mac_addresses", arp)
    monkeypatch.setattr("app.api.devices.get_vendor", lambda mac: None)

    body = (await client.post(f"/api/devices/{dev.id}/refresh-info", headers=auth)).json()

    assert (body["display_name"], body["hostname"]) == ("Keller-NAS", "nas01.lan")
    arp.assert_not_awaited()  # the MAC is known already


@pytest.mark.asyncio
async def test_refresh_info_unknown_device(client, auth):
    assert (await client.post("/api/devices/999/refresh-info", headers=auth)).status_code == 404


# --- refresh-services ---------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_services_adds_found_ports_and_marks_gone_ones_down(client, db, auth, monkeypatch):
    dev = await _device(db)
    db.add_all([
        Service(device_id=dev.id, name="HTTP", protocol="http", port=80, url_template="http://{ip}", is_auto_detected=True, is_up=True),
        Service(device_id=dev.id, name="Service 22", protocol="tcp", port=22, url_template="", is_auto_detected=True, is_up=False),
        Service(device_id=dev.id, name="Mein Dienst", protocol="http", port=81, url_template="", is_auto_detected=False, is_up=True),
    ])
    await db.commit()
    monkeypatch.setattr("app.scanner.port_scanner.nmap_scan", AsyncMock(return_value=[22, 12345]))

    res = await client.post(f"/api/devices/{dev.id}/refresh-services", headers=auth)

    assert res.status_code == 200, res.text
    services = await _services(db, dev.id)
    assert services[80].is_up is False          # auto-detected, no longer open
    assert services[81].is_up is True           # added by hand: the scan leaves it alone
    assert (services[22].name, services[22].is_up) == ("SSH", True)  # a placeholder name gets the real one
    assert services[12345].name == "Port 12345"


@pytest.mark.asyncio
async def test_refresh_services_falls_back_to_the_socket_scan(client, db, auth, monkeypatch):
    dev = await _device(db)
    monkeypatch.setattr("app.scanner.port_scanner.nmap_scan", AsyncMock(return_value=[]))
    fallback = AsyncMock(return_value=[443])
    monkeypatch.setattr("app.scanner.port_scanner.scan_ports", fallback)

    assert (await client.post(f"/api/devices/{dev.id}/refresh-services", headers=auth)).status_code == 200

    fallback.assert_awaited_once()
    assert list(await _services(db, dev.id)) == [443]


@pytest.mark.asyncio
async def test_refresh_services_unknown_device(client, auth):
    assert (await client.post("/api/devices/999/refresh-services", headers=auth)).status_code == 404


# --- refresh-all ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_all_updates_devices_in_the_background(client, db, auth, monkeypatch):
    dev = await _device(db)

    class SameSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_exc):
            pass

    monkeypatch.setattr("app.database.async_session", SameSession)
    monkeypatch.setattr("app.scanner.hostname.resolve_hostname", AsyncMock(return_value="printer.lan"))

    async def fake_arp(hosts):
        for h in hosts:
            h["mac"] = "aa:bb:cc:dd:ee:03"

    monkeypatch.setattr("app.scanner.arp.resolve_mac_addresses", fake_arp)
    monkeypatch.setattr("app.api.devices.get_vendor", lambda mac: "Brother")

    res = await client.post("/api/devices/refresh-all", headers=auth)

    assert res.status_code == 200, res.text
    await db.refresh(dev)
    assert (dev.hostname, dev.display_name, dev.mac, dev.vendor) == ("printer.lan", "printer", "aa:bb:cc:dd:ee:03", "Brother")


# --- history read state ---------------------------------------------------------

@pytest.mark.asyncio
async def test_history_read_all_marks_only_this_device(client, db, auth):
    dev = await _device(db)
    other = await _device(db, ip="192.0.2.31", display_name="other")
    db.add_all([
        DeviceHistory(device_id=dev.id, status="offline", read=False),
        DeviceHistory(device_id=dev.id, status="online", read=False),
        DeviceHistory(device_id=other.id, status="offline", read=False),
    ])
    await db.commit()

    res = await client.post(f"/api/devices/{dev.id}/history/read-all", headers=auth)

    assert res.json()["marked_read"] == 2
    history = (await client.get(f"/api/devices/{other.id}/history", headers=auth)).json()
    assert [h["read"] for h in history] == [False]


# --- services -------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol", "template"),
    [("https", "https://{ip}:{port}"), ("ssh", "ssh://{ip}:{port}"), ("smb", "smb://{ip}"), ("tcp", "")],
)
async def test_add_service_fills_in_a_link(client, db, auth, protocol, template):
    dev = await _device(db)

    res = await client.post(f"/api/devices/{dev.id}/services", json={"name": "Svc", "protocol": protocol, "port": 8443}, headers=auth)

    assert res.status_code == 200, res.text
    assert res.json()["url_template"] == template


@pytest.mark.asyncio
async def test_add_service_unknown_device(client, auth):
    res = await client.post("/api/devices/999/services", json={"name": "Svc", "port": 80}, headers=auth)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_update_service_switches_the_link_and_keeps_it_from_the_scan(client, db, auth):
    dev = await _device(db)
    svc = Service(device_id=dev.id, name="Web", protocol="http", port=80, url_template="http://{ip}:{port}", is_auto_detected=True)
    db.add(svc)
    await db.commit()

    res = await client.patch(f"/api/services/{svc.id}", json={"protocol": "https"}, headers=auth)

    assert res.status_code == 200, res.text
    assert (res.json()["url_template"], res.json()["is_auto_detected"]) == ("https://{ip}:{port}", False)


@pytest.mark.asyncio
async def test_update_service_ssl_toggle_resets_its_state(client, db, auth):
    dev = await _device(db)
    svc = Service(device_id=dev.id, name="Web", protocol="https", port=443, url_template="https://{ip}",
                  ssl_expiry_days=12, ssl_checked_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    db.add(svc)
    await db.commit()

    await client.patch(f"/api/services/{svc.id}", json={"ignore_ssl": True}, headers=auth)
    await db.refresh(svc)
    assert svc.ssl_expiry_days is None

    await client.patch(f"/api/services/{svc.id}", json={"ignore_ssl": False}, headers=auth)
    await db.refresh(svc)
    assert svc.ssl_checked_at is None


@pytest.mark.asyncio
async def test_update_and_delete_unknown_service(client, auth):
    assert (await client.patch("/api/services/999", json={"name": "x"}, headers=auth)).status_code == 404
    assert (await client.delete("/api/services/999", headers=auth)).status_code == 404


@pytest.mark.asyncio
async def test_delete_service(client, db, auth):
    dev = await _device(db)
    svc = Service(device_id=dev.id, name="Web", protocol="http", port=80, url_template="")
    db.add(svc)
    await db.commit()

    assert (await client.delete(f"/api/services/{svc.id}", headers=auth)).status_code == 204
    assert await _services(db, dev.id) == {}
