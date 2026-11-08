"""The topology API (app/api/topology.py): racks (create, resize guarded by what sits in them,
delete), links (create, partial update keeping the role, delete), the cached map and its nodes."""

import pytest
from sqlalchemy import select

from app.models.device import Device
from app.models.topology import Rack, TopologyLink
from app.services.cache_service import topology_cache


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(autouse=True)
def fresh_cache():
    topology_cache.invalidate()
    yield
    topology_cache.invalidate()


async def test_rack_lifecycle(client, auth, db):
    created = (await client.post("/api/topology/racks", json={"name": "Main", "units": 24}, headers=auth)).json()
    assert (created["name"], created["units"], created["width"]) == ("Main", 24, 19)
    assert [r["name"] for r in (await client.get("/api/topology/racks", headers=auth)).json()] == ["Main"]

    renamed = await client.patch(f"/api/topology/racks/{created['id']}", json={"name": "Core", "width": 10}, headers=auth)
    assert (renamed.json()["name"], renamed.json()["width"]) == ("Core", 10)

    assert (await client.delete(f"/api/topology/racks/{created['id']}", headers=auth)).json() == {"message": "Rack deleted"}
    assert (await db.execute(select(Rack))).scalars().all() == []


async def test_rack_patch_errors(client, auth, db):
    rack = Rack(name="Main", units=24)
    db.add(rack)
    await db.flush()
    db.add(Device(ip="192.0.2.10", display_name="Switch", rack_id=rack.id, rack_unit=20, rack_height=2))
    await db.commit()

    assert (await client.patch("/api/topology/racks/9999", json={"name": "x"}, headers=auth)).status_code == 404
    cleared = await client.patch(f"/api/topology/racks/{rack.id}", json={"name": None}, headers=auth)
    assert cleared.status_code == 422
    too_small = await client.patch(f"/api/topology/racks/{rack.id}", json={"units": 12}, headers=auth)
    assert too_small.status_code == 409
    assert "Switch sits on unit 20" in too_small.json()["detail"]
    fits = await client.patch(f"/api/topology/racks/{rack.id}", json={"units": 20}, headers=auth)
    assert fits.json()["units"] == 20


async def test_link_lifecycle(client, auth, db):
    a, b = Device(ip="192.0.2.1"), Device(ip="192.0.2.2")
    db.add_all([a, b])
    await db.commit()

    link = (await client.post("/api/topology/links", json={"source_id": a.id, "target_id": b.id}, headers=auth)).json()
    assert link["link_type"] == "1GbE"
    role = (await db.execute(select(TopologyLink.role))).scalar_one()

    updated = await client.patch(f"/api/topology/links/{link['id']}", json={"link_type": "10GbE", "role": None}, headers=auth)
    assert updated.json()["link_type"] == "10GbE"
    assert updated.json()["role"] == role  # null means "leave it"
    assert (await client.patch("/api/topology/links/9999", json={"color": "#fff"}, headers=auth)).status_code == 404

    assert [x["id"] for x in (await client.get("/api/topology/links", headers=auth)).json()] == [link["id"]]
    assert (await client.delete(f"/api/topology/links/{link['id']}", headers=auth)).json() == {"message": "Link deleted"}


async def test_map_is_cached_and_nodes_come_from_it(client, auth, db):
    db.add(Device(ip="192.0.2.1", hostname="router"))
    await db.commit()

    first = (await client.get("/api/topology/map", headers=auth)).json()
    assert [d["ip"] for d in first["devices"]] == ["192.0.2.1"]

    # A device added behind the API's back is not seen while the cache is fresh
    db.add(Device(ip="192.0.2.2"))
    await db.commit()
    nodes = (await client.get("/api/topology/nodes", headers=auth)).json()
    assert [d["ip"] for d in nodes] == ["192.0.2.1"]

    topology_cache.invalidate()
    refreshed = (await client.get("/api/topology/map", headers=auth)).json()
    assert sorted(d["ip"] for d in refreshed["devices"]) == ["192.0.2.1", "192.0.2.2"]
