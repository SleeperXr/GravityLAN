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
async def test_refresh_services_keeps_the_type_when_the_scan_recognises_nothing(client, db, auth, monkeypatch):
    """The classifier answers "unknown" when no rule matches; that must not replace a known type."""
    dev = await _device(db, device_type="nas", device_subtype="Synology")
    monkeypatch.setattr("app.scanner.port_scanner.nmap_scan", AsyncMock(return_value=[12345]))

    assert (await client.post(f"/api/devices/{dev.id}/refresh-services", headers=auth)).status_code == 200

    await db.refresh(dev)
    assert dev.device_type == "nas"


@pytest.mark.asyncio
async def test_refresh_services_still_sets_a_recognised_type(client, db, auth, monkeypatch):
    dev = await _device(db, device_type="unknown")
    monkeypatch.setattr("app.scanner.port_scanner.nmap_scan", AsyncMock(return_value=[22]))

    assert (await client.post(f"/api/devices/{dev.id}/refresh-services", headers=auth)).status_code == 200

    await db.refresh(dev)
    assert dev.device_type == "server"


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
@pytest.mark.parametrize("template", [
    "http://{ip}/admin",            # a path
    "http://{ip}:8080/ui?x=1",      # a path and query
    "http://{ip}:9443",             # another port than the service's
    "http://nas.lan:{port}",        # a name instead of the IP
])
async def test_update_service_keeps_a_custom_link_when_the_protocol_changes(client, db, auth, template):
    dev = await _device(db)
    svc = Service(device_id=dev.id, name="Web", protocol="http", port=80, url_template=template)
    db.add(svc)
    await db.commit()

    res = await client.patch(f"/api/services/{svc.id}", json={"protocol": "https"}, headers=auth)

    assert res.status_code == 200, res.text
    assert res.json()["url_template"] == template


@pytest.mark.asyncio
@pytest.mark.parametrize("template", ["http://{ip}", "http://{ip}:{port}", "http://{ip}:5000", "", None])
async def test_update_service_replaces_a_generated_link_when_the_protocol_changes(client, db, auth, template):
    dev = await _device(db)
    svc = Service(device_id=dev.id, name="DSM", protocol="http", port=5000, url_template=template)
    db.add(svc)
    await db.commit()

    res = await client.patch(f"/api/services/{svc.id}", json={"protocol": "https"}, headers=auth)

    assert res.json()["url_template"] == "https://{ip}:{port}"


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

    assert ( await client.delete(f"/api/services/{svc.id}", headers=auth)).status_code == 204
    assert await _services(db, dev.id) == {}


# --- device & group edge cases ------------------------------------------------

@pytest.mark.asyncio
async def test_get_update_delete_device_and_edge_cases(client, db, auth, monkeypatch):
    dev = await _device(db, ip="192.0.2.80", display_name="srv")
    dev_id = dev.id
    db.expunge_all()

    # get_device found and 404
    res = await client.get(f"/api/devices/{dev_id}", headers=auth)
    assert res.status_code == 200 and res.json()["ip"] == "192.0.2.80"
    assert (await client.get("/api/devices/9999", headers=auth)).status_code == 404

    # update_device 404
    assert (await client.patch("/api/devices/9999", json={"display_name": "x"}, headers=auth)).status_code == 404

    # _set_hostname_source invalid JSON in dns_names
    dev = await db.get(Device, dev_id)
    dev.dns_names = "{invalid-json"
    await db.commit()
    res_patch = await client.patch(f"/api/devices/{dev_id}", json={"hostname_source": "dns1"}, headers=auth)
    assert res_patch.status_code == 200

    # delete_device 404 & empty bulk-delete / _delete_device_dependencies
    assert (await client.delete("/api/devices/9999", headers=auth)).status_code == 404
    assert (await client.post("/api/devices/bulk-delete", json=[], headers=auth)).status_code == 204
    from app.api.devices import _delete_device_dependencies
    await _delete_device_dependencies(db, [])

    # refresh_services adds missing port and marks existing un-classified port up when classification returns None
    db.add(Service(device_id=dev_id, name="Custom", protocol="tcp", port=9999, url_template="", is_auto_detected=False, is_up=False))
    await db.commit()
    db.expunge_all()
    monkeypatch.setattr("app.scanner.port_scanner.nmap_scan", AsyncMock(return_value=[9998, 9999]))
    monkeypatch.setattr("app.scanner.classifier.classify_device", lambda _d: None)
    assert (await client.post(f"/api/devices/{dev_id}/refresh-services", headers=auth)).status_code == 200
    svcs = await _services(db, dev_id)
    assert svcs[9999].is_up is True
    assert svcs[9998].name == "Service 9998"

    # refresh_all per-device error handling
    class SameSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_exc):
            pass

    monkeypatch.setattr("app.database.async_session", SameSession)
    monkeypatch.setattr("app.scanner.arp.resolve_mac_addresses", AsyncMock())
    monkeypatch.setattr("app.scanner.hostname.resolve_hostname", AsyncMock(side_effect=RuntimeError("boom")))
    assert (await client.post("/api/devices/refresh-all", headers=auth)).status_code == 200

    # refresh_all endpoint error handling (500)
    from fastapi import HTTPException
    from app.api.devices import refresh_all_devices

    async def broken_dns(_db):
        raise RuntimeError("db error")

    monkeypatch.setattr("app.api.devices._dns_servers", broken_dns)
    with pytest.raises(HTTPException) as exc_info:
        await refresh_all_devices(background_tasks=None, db=db)
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_group_edge_cases(client, db, auth):
    from app.models.device import DeviceGroup
    default_grp = DeviceGroup(name="Default", is_default=True)
    db.add(default_grp)
    await db.commit()

    # list_groups with items
    res = await client.get("/api/groups", headers=auth)
    assert res.status_code == 200 and len(res.json()) >= 1

    # create_group empty name
    assert (await client.post("/api/groups", json={"name": "   "}, headers=auth)).status_code == 400

    # update_group 404
    assert (await client.patch("/api/groups/9999", json={"name": "New"}, headers=auth)).status_code == 404

    # delete_group 404 and default group protection
    assert (await client.delete("/api/groups/9999", headers=auth)).status_code == 404
    assert (await client.delete(f"/api/groups/{default_grp.id}", headers=auth)).status_code == 400

    # get_group_details 404
    assert (await client.get("/api/groups/9999", headers=auth)).status_code == 404

