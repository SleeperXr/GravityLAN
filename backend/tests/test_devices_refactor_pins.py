"""Behaviour of app/api/devices.py pinned before its refactor.

Covers what the existing device tests leave open: agent and parent annotations in the device list,
the details a new device gets from add-from-ip, the per-device rules of the bulk metadata refresh,
default service links per protocol, and how a service scan refreshes auto-detected services.
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.agent import AgentToken
from app.models.device import Device, DeviceHistory, Service
from app.services.cache_service import dashboard_cache


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(autouse=True)
def fresh_cache():
    dashboard_cache.invalidate_all()
    yield
    dashboard_cache.invalidate_all()


async def _device(db, **fields) -> Device:
    dev = Device(ip=fields.pop("ip", "192.0.2.30"), display_name=fields.pop("display_name", "192.0.2.30"), **fields)
    db.add(dev)
    await db.commit()
    return dev


# --- list ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_annotates_agents_and_parent_names(client, db, auth):
    host = await _device(db, ip="192.0.2.10", display_name="pve")
    hidden_host = await _device(db, ip="192.0.2.11", display_name="hidden-host", is_hidden=True)
    vm = await _device(db, ip="192.0.2.12", display_name="vm1", parent_id=host.id)
    vm2 = await _device(db, ip="192.0.2.13", display_name="vm2", parent_id=hidden_host.id)
    unnamed_parent = await _device(db, ip="192.0.2.14", display_name="")
    vm3 = await _device(db, ip="192.0.2.15", display_name="vm3", parent_id=unnamed_parent.id)
    db.add_all([
        AgentToken(device_id=host.id, token="tok-host", agent_version="v0.6.0"),
        AgentToken(device_id=vm.id, token="tok-vm", agent_version=None, pending_token="pending-hash"),
    ])
    await db.commit()

    data = {d["ip"]: d for d in (await client.get("/api/devices", headers=auth)).json()}

    assert "192.0.2.11" not in data
    assert (data["192.0.2.10"]["has_agent"], data["192.0.2.10"]["has_pending_token"]) == (True, False)
    assert data["192.0.2.10"]["agent_info"]["agent_version"] == "0.6.0"
    assert data["192.0.2.10"]["agent_info"]["latest_version"]
    assert (data["192.0.2.12"]["has_agent"], data["192.0.2.12"]["has_pending_token"]) == (True, True)
    assert data["192.0.2.12"]["agent_info"]["agent_version"] is None
    assert (data["192.0.2.13"]["has_agent"], data["192.0.2.13"]["agent_info"]) == (False, None)
    assert data["192.0.2.12"]["parent_name"] == "pve"
    assert data["192.0.2.13"]["parent_name"] == "hidden-host"      # parent outside the list
    assert data["192.0.2.15"]["parent_name"] == "192.0.2.14"       # a parent without a name shows its IP
    assert data["192.0.2.10"]["parent_name"] is None

    with_hidden = {d["ip"] for d in (await client.get("/api/devices?include_hidden=true", headers=auth)).json()}
    assert "192.0.2.11" in with_hidden
    by_group = (await client.get("/api/devices?group_id=999", headers=auth)).json()
    assert by_group == []


@pytest.mark.asyncio
async def test_list_answers_from_the_cache_until_it_is_invalidated(client, db, auth):
    await _device(db, ip="192.0.2.20", display_name="first")
    assert len((await client.get("/api/devices", headers=auth)).json()) == 1
    await _device(db, ip="192.0.2.21", display_name="second")
    assert len((await client.get("/api/devices", headers=auth)).json()) == 1
    dashboard_cache.invalidate_all()
    assert len((await client.get("/api/devices", headers=auth)).json()) == 2


# --- add-from-ip ------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(("hostname", "display"), [("nas01.home.lan", "nas01"), ("192.0.2.40", "192.0.2.40"), (None, "192.0.2.40")])
async def test_add_from_ip_fills_name_mac_and_vendor(client, db, auth, monkeypatch, hostname, display):
    monkeypatch.setattr("app.scanner.hostname.resolve_hostname", AsyncMock(return_value=hostname))

    async def fake_arp(hosts, *a, **k):
        hosts[0]["mac"] = "aa:bb:cc:00:00:40"
        return hosts

    monkeypatch.setattr("app.scanner.arp.resolve_mac_addresses", fake_arp)
    monkeypatch.setattr("app.api.devices.get_vendor", lambda mac: "Synology")

    res = await client.post("/api/devices/add-from-ip?ip=192.0.2.40", headers=auth)

    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["display_name"], body["hostname"], body["mac"], body["vendor"]) == (display, hostname, "aa:bb:cc:00:00:40", "Synology")
    assert body["device_type"] == "Unbekannt"
    history = (await db.execute(select(DeviceHistory).where(DeviceHistory.device_id == body["id"]))).scalars().all()
    assert [h.status for h in history] == ["new_device"]


@pytest.mark.asyncio
async def test_add_from_ip_keeps_the_device_when_the_lookups_fail(client, db, auth, monkeypatch):
    monkeypatch.setattr("app.scanner.hostname.resolve_hostname", AsyncMock(side_effect=RuntimeError("dns down")))

    res = await client.post("/api/devices/add-from-ip?ip=192.0.2.41", headers=auth)

    assert res.status_code == 200
    assert (res.json()["display_name"], res.json()["mac"]) == ("192.0.2.41", None)


@pytest.mark.asyncio
async def test_add_from_ip_returns_a_known_device_and_rejects_bad_input(client, db, auth, monkeypatch):
    dev = await _device(db, ip="192.0.2.42", display_name="known")
    lookup = AsyncMock(return_value="x")
    monkeypatch.setattr("app.scanner.hostname.resolve_hostname", lookup)

    res = await client.post("/api/devices/add-from-ip?ip=192.0.2.42", headers=auth)
    assert (res.status_code, res.json()["id"], res.json()["display_name"]) == (200, dev.id, "known")
    lookup.assert_not_awaited()
    assert (await client.post("/api/devices/add-from-ip?ip=not-an-ip", headers=auth)).status_code == 400


# --- refresh-all --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_refresh_rules_per_device(client, db, auth, monkeypatch):
    nameless = await _device(db, ip="192.0.2.50", display_name="192.0.2.50")
    named = await _device(db, ip="192.0.2.51", display_name="My NAS", hostname="old.lan", mac="aa:aa:aa:aa:aa:51", vendor="Old")
    same = await _device(db, ip="192.0.2.52", display_name="same", hostname="same.lan", mac="aa:aa:aa:aa:aa:52", vendor="Brother")
    unresolved = await _device(db, ip="192.0.2.53", display_name="192.0.2.53")

    class SameSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_exc):
            pass

    names = {"192.0.2.50": "printer.lan", "192.0.2.51": "nas.lan", "192.0.2.52": "same.lan", "192.0.2.53": "192.0.2.53"}

    async def fake_resolve(ip, dns_server=None, **_kw):
        return names[ip]

    async def fake_arp(hosts, *a, **k):
        for h in hosts:
            if h["ip"] in ("192.0.2.50", "192.0.2.51"):
                h["mac"] = "bb:bb:bb:bb:bb:" + h["ip"].rsplit(".", 1)[1]
        return hosts

    monkeypatch.setattr("app.database.async_session", SameSession)
    monkeypatch.setattr("app.scanner.hostname.resolve_hostname", fake_resolve)
    monkeypatch.setattr("app.scanner.arp.resolve_mac_addresses", fake_arp)
    monkeypatch.setattr("app.api.devices.get_vendor", lambda mac: "Brother" if mac.endswith("52") or mac.startswith("bb") else None)

    res = await client.post("/api/devices/refresh-all", headers=auth)
    assert res.status_code == 200
    assert "4 devices" in res.json()["message"]

    for dev in (nameless, named, same, unresolved):
        await db.refresh(dev)
    # no MAC yet: takes the one ARP found, and the vendor and short name follow
    assert (nameless.mac, nameless.vendor, nameless.hostname, nameless.display_name) == (
        "bb:bb:bb:bb:bb:50", "Brother", "printer.lan", "printer")
    # a known MAC stays; no vendor found keeps the old one; a chosen display name stays
    assert (named.mac, named.vendor, named.hostname, named.display_name) == ("aa:aa:aa:aa:aa:51", "Old", "nas.lan", "My NAS")
    assert (same.hostname, same.vendor) == ("same.lan", "Brother")
    # an IP-like answer is stored as hostname but does not rename the device
    assert (unresolved.hostname, unresolved.display_name) == ("192.0.2.53", "192.0.2.53")


# --- service links ----------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(("protocol", "template", "expected"), [
    ("SSH", None, "ssh://{ip}:{port}"),
    ("smb", "", "smb://{ip}"),
    ("ftp", "", ""),
    ("ftp", None, ""),  # no link sent: the schema's empty default stays
    ("https", "https://{ip}/ui", "https://{ip}/ui"),
])
async def test_add_service_default_links(client, db, auth, protocol, template, expected):
    dev = await _device(db)
    payload = {"name": "S", "protocol": protocol, "port": 21}
    if template is not None:
        payload["url_template"] = template
    res = await client.post(f"/api/devices/{dev.id}/services", json=payload, headers=auth)
    assert res.status_code == 200, res.text
    assert res.json()["url_template"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(("protocol", "expected"), [("ssh", "ssh://{ip}:{port}"), ("SMB", "smb://{ip}"), ("ftp", "http://{ip}:{port}")])
async def test_update_service_protocol_sets_the_default_link_or_keeps_it(client, db, auth, protocol, expected):
    dev = await _device(db)
    svc = Service(device_id=dev.id, name="Web", protocol="http", port=80, url_template="http://{ip}:{port}")
    db.add(svc)
    await db.commit()
    res = await client.patch(f"/api/services/{svc.id}", json={"protocol": protocol}, headers=auth)
    assert res.json()["url_template"] == expected


# --- service scan ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_scan_refreshes_auto_services_from_the_templates(client, db, auth, monkeypatch):
    dev = await _device(db)
    db.add_all([
        Service(device_id=dev.id, name="Service 5001", protocol="tcp", port=5001, url_template="", color="#34495e", is_auto_detected=True, is_up=False),
        Service(device_id=dev.id, name="Mein DSM", protocol="https", port=5000, url_template="", color=None, is_auto_detected=False, is_up=False),
    ])
    await db.commit()
    monkeypatch.setattr("app.scanner.port_scanner.nmap_scan", AsyncMock(return_value=[5000, 5001, 445]))

    assert (await client.post(f"/api/devices/{dev.id}/refresh-services", headers=auth)).status_code == 200

    query = select(Service).where(Service.device_id == dev.id).execution_options(populate_existing=True)
    rows = {s.port: s for s in (await db.execute(query)).scalars().all()}
    assert rows[5001].name != "Service 5001" and rows[5001].color != "#34495e" and rows[5001].is_up
    assert (rows[5000].name, rows[5000].color, rows[5000].is_up) == ("Mein DSM", None, True)
    assert rows[445].is_auto_detected is True
