"""presence_frozen: a device with an open MAC conflict is not probed, and every API that shows its online state
says so, so the last known state is not read as a measured one (app.services.mac_observations)."""

import pytest

from app.models.agent import AgentConfig, AgentToken
from app.models.device import Device
from app.models.network import Subnet
from app.services import mac_observations
from app.services.agent_scanner_relay import ingest_agent_arp_table
from app.services.cache_service import dashboard_cache

MAC_A = "00:11:22:33:44:aa"
MAC_B = "00:11:22:33:44:bb"


@pytest.fixture(autouse=True)
def empty_device_cache():
    """The list cache is process-wide: a list another test cached must not answer here."""
    dashboard_cache.invalidate_all()
    yield
    dashboard_cache.invalidate_all()


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


async def add_devices(db):
    nas = Device(ip="192.168.110.10", mac=MAC_A, display_name="NAS", is_online=True)
    printer = Device(ip="192.168.110.11", mac="00:11:22:33:44:cc", display_name="Printer", is_online=True)
    db.add_all([nas, printer])
    await db.commit()
    return nas, printer


async def open_conflict(db, device):
    assert await mac_observations.record_mac_conflict(db, device, MAC_B, "scan") is True
    await db.commit()


async def frozen_in_list(client, auth) -> dict[str, bool]:
    response = await client.get("/api/devices", headers=auth)
    assert response.status_code == 200
    return {d["display_name"]: d["presence_frozen"] for d in response.json()}


async def test_the_device_endpoints_mark_a_device_with_an_open_conflict(db, client, auth):
    nas, printer = await add_devices(db)
    await open_conflict(db, nas)

    assert await frozen_in_list(client, auth) == {"NAS": True, "Printer": False}
    assert (await client.get(f"/api/devices/{nas.id}", headers=auth)).json()["presence_frozen"] is True
    assert (await client.get(f"/api/devices/{printer.id}", headers=auth)).json()["presence_frozen"] is False
    patched = await client.patch(f"/api/devices/{nas.id}", json={"notes": "edited"}, headers=auth)
    assert patched.status_code == 200
    assert patched.json()["presence_frozen"] is True


async def test_dismissing_the_conflict_unfreezes_the_device(db, client, auth):
    nas, _ = await add_devices(db)
    await open_conflict(db, nas)
    assert (await frozen_in_list(client, auth))["NAS"] is True

    response = await client.post(f"/api/devices/{nas.id}/mac-observations/dismiss", json={"mac": MAC_B}, headers=auth)
    assert response.status_code == 204

    assert (await frozen_in_list(client, auth))["NAS"] is False


async def test_adopting_the_mac_unfreezes_the_device(db, client, auth):
    nas, _ = await add_devices(db)
    await open_conflict(db, nas)
    assert (await frozen_in_list(client, auth))["NAS"] is True

    response = await client.put(f"/api/devices/{nas.id}/mac", json={"mac": MAC_B}, headers=auth)
    assert response.status_code == 200

    assert (await frozen_in_list(client, auth))["NAS"] is False


async def test_a_conflict_the_relay_finds_shows_in_the_cached_list_at_once(db, client, auth):
    nas, _ = await add_devices(db)
    probe = Device(ip="192.168.110.128", display_name="Probe", is_online=True)
    db.add(probe)
    await db.flush()
    db.add(AgentToken(device_id=probe.id, token="probe-token", is_active=True))
    db.add(AgentConfig(device_id=probe.id, enable_scanner_relay=True))
    db.add(Subnet(name="lan", cidr="192.168.110.0/24", is_enabled=True))
    await db.commit()
    assert (await frozen_in_list(client, auth))["NAS"] is False  # the list is cached now

    await ingest_agent_arp_table(db, probe.id, [{"ip": nas.ip, "mac": MAC_B}])

    assert (await frozen_in_list(client, auth))["NAS"] is True


async def test_the_health_views_mark_a_device_with_an_open_conflict(db, client, auth):
    nas, printer = await add_devices(db)
    await open_conflict(db, nas)

    overview = await client.get("/api/health/overview", headers=auth)
    assert overview.status_code == 200
    assert {d["display_name"]: d["presence_frozen"] for d in overview.json()["devices"]} == {"NAS": True, "Printer": False}
    detail = await client.get(f"/api/health/device/{nas.id}", headers=auth)
    assert detail.json()["device"]["presence_frozen"] is True
    other = await client.get(f"/api/health/device/{printer.id}", headers=auth)
    assert other.json()["device"]["presence_frozen"] is False
