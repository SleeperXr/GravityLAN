"""Edges of the rack cabling API (app/api/rack_cabling.py): unknown racks, items and owners,
units taken by another rack item, shrinking a port count, and editing or deleting cables."""

import pytest

from app.models.device import Device
from app.models.topology import Rack


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
async def rack(db):
    r = Rack(name="Main", units=12)
    db.add(r)
    await db.commit()
    return r


async def _item(client, auth, rack, **kw):
    body = {"rack_id": rack.id, "name": "Patch panel", "kind": "patch_copper", "rack_unit": 10, "port_count": 4, **kw}
    res = await client.post("/api/topology/rack-items", json=body, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def test_unknown_rack_and_unit_taken_by_another_item(client, auth, rack):
    missing = await client.post("/api/topology/rack-items", json={"rack_id": 9999, "name": "x"}, headers=auth)
    assert missing.status_code == 404
    await _item(client, auth, rack)
    taken = await client.post("/api/topology/rack-items", json={"rack_id": rack.id, "name": "UPS", "rack_unit": 10}, headers=auth)
    assert taken.status_code == 409
    assert taken.json()["detail"] == "Unit already taken by Patch panel"


async def test_unknown_item_on_patch_and_delete(client, auth):
    assert (await client.patch("/api/topology/rack-items/9999", json={"name": "x"}, headers=auth)).status_code == 404
    assert (await client.delete("/api/topology/rack-items/9999", headers=auth)).status_code == 404


async def test_shrinking_the_port_count_removes_free_ports(client, auth, rack):
    item = await _item(client, auth, rack)
    body = {"owner_type": "item", "owner_id": item["id"], "count": 2}
    res = await client.put("/api/topology/ports", json=body, headers=auth)
    assert [p["number"] for p in res.json()] == [1, 2]
    unknown = await client.put("/api/topology/ports", json={"owner_type": "device", "owner_id": 9999, "count": 2}, headers=auth)
    assert unknown.status_code == 404


async def test_cable_edit_and_delete(client, auth, rack, db):
    dev = Device(ip="192.0.2.10", display_name="Switch")
    db.add(dev)
    await db.commit()
    item = await _item(client, auth, rack)
    item_ports = (await client.get("/api/topology/cabling", headers=auth)).json()["ports"]
    body = {"owner_type": "device", "owner_id": dev.id, "count": 1}
    device_ports = (await client.put("/api/topology/ports", json=body, headers=auth)).json()
    a = next(p["id"] for p in item_ports if p["rack_item_id"] == item["id"])

    unknown_port = await client.post("/api/topology/rack-cables", json={"a_port_id": a, "b_port_id": 99999}, headers=auth)
    assert unknown_port.status_code == 404
    created = await client.post("/api/topology/rack-cables", json={"a_port_id": a, "b_port_id": device_ports[0]["id"]}, headers=auth)
    cable = created.json()

    edit = {"cable": "Cat6a", "color": "#ff0000", "notes": "uplink"}
    edited = (await client.patch(f"/api/topology/rack-cables/{cable['id']}", json=edit, headers=auth)).json()
    assert (edited["cable"], edited["color"], edited["notes"]) == ("Cat6a", "#ff0000", "uplink")
    cleared = await client.patch(f"/api/topology/rack-cables/{cable['id']}", json={"cable": None}, headers=auth)
    assert cleared.status_code == 422
    assert (await client.patch("/api/topology/rack-cables/9999", json={"notes": "x"}, headers=auth)).status_code == 404

    assert (await client.delete(f"/api/topology/rack-cables/{cable['id']}", headers=auth)).json() == {"message": "Cable deleted"}
    assert (await client.delete(f"/api/topology/rack-cables/{cable['id']}", headers=auth)).status_code == 404
