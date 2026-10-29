"""Rack equipment, ports and rack cables: placement, port counts and the one-cable-per-port rule."""

import pytest

from app.models.device import Device
from app.models.topology import Rack

HEADERS = {"Authorization": "Bearer test-admin-token-12345"}


async def _rack_with_server(db):
    rack = Rack(name="Rack A", units=12)
    db.add(rack)
    await db.flush()
    server = Device(ip="10.0.0.10", display_name="pve-01", rack_id=rack.id, rack_unit=6, rack_height=2)
    db.add(server)
    await db.commit()
    return rack, server


def _item(rack_id, **extra):
    return {"rack_id": rack_id, "name": "Patchfeld", "kind": "patch_copper", "rack_unit": 2, "rack_height": 1, "port_count": 0, **extra}


async def _cabling(client):
    return (await client.get("/api/topology/cabling", headers=HEADERS)).json()


@pytest.mark.asyncio
async def test_item_takes_a_free_unit_and_refuses_taken_ones(client, db, admin_token):
    rack, _ = await _rack_with_server(db)

    free = await client.post("/api/topology/rack-items", json=_item(rack.id, rack_unit=2), headers=HEADERS)
    assert free.status_code == 200

    # The server covers units 6 and 5 (its top unit is 6, height 2)
    taken = await client.post("/api/topology/rack-items", json=_item(rack.id, rack_unit=5), headers=HEADERS)
    assert taken.status_code == 409
    assert "pve-01" in taken.json()["detail"]


@pytest.mark.asyncio
async def test_item_must_fit_inside_the_rack(client, db, admin_token):
    rack, _ = await _rack_with_server(db)
    response = await client.post("/api/topology/rack-items", json=_item(rack.id, rack_unit=1, rack_height=2), headers=HEADERS)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_moving_an_item_checks_the_new_place(client, db, admin_token):
    rack, _ = await _rack_with_server(db)
    item = (await client.post("/api/topology/rack-items", json=_item(rack.id, rack_unit=2), headers=HEADERS)).json()

    blocked = await client.patch(f"/api/topology/rack-items/{item['id']}", json={"rack_unit": 6}, headers=HEADERS)
    assert blocked.status_code == 409

    moved = await client.patch(f"/api/topology/rack-items/{item['id']}", json={"rack_unit": 9}, headers=HEADERS)
    assert moved.status_code == 200 and moved.json()["rack_unit"] == 9

    # A required field cannot be cleared; unplacing (rack_unit null) is allowed
    cleared = await client.patch(f"/api/topology/rack-items/{item['id']}", json={"name": None}, headers=HEADERS)
    assert cleared.status_code == 422
    tray = await client.patch(f"/api/topology/rack-items/{item['id']}", json={"rack_unit": None}, headers=HEADERS)
    assert tray.status_code == 200 and tray.json()["rack_unit"] is None


@pytest.mark.asyncio
async def test_ports_follow_the_count_but_keep_cabled_ones(client, db, admin_token):
    rack, server = await _rack_with_server(db)
    item = (await client.post("/api/topology/rack-items", json=_item(rack.id, port_count=4), headers=HEADERS)).json()
    assert sorted(p["number"] for p in (await _cabling(client))["ports"] if p["rack_item_id"] == item["id"]) == [1, 2, 3, 4]

    grown = await client.put("/api/topology/ports", json={"owner_type": "item", "owner_id": item["id"], "count": 6, "kind": "RJ45"}, headers=HEADERS)
    assert [p["number"] for p in grown.json()] == [1, 2, 3, 4, 5, 6]

    # Cable the server's port to item port 4, then try to shrink below it: refused, nothing is removed
    server_port = await client.put("/api/topology/ports", json={"owner_type": "device", "owner_id": server.id, "count": 1, "kind": "RJ45"}, headers=HEADERS)
    cable = await client.post(
        "/api/topology/rack-cables", json={"a_port_id": server_port.json()[0]["id"], "b_port_id": grown.json()[3]["id"]}, headers=HEADERS
    )
    assert cable.status_code == 200
    shrunk = await client.put("/api/topology/ports", json={"owner_type": "item", "owner_id": item["id"], "count": 2, "kind": "RJ45"}, headers=HEADERS)
    assert shrunk.status_code == 409
    assert len([p for p in (await _cabling(client))["ports"] if p["rack_item_id"] == item["id"]]) == 6


@pytest.mark.asyncio
async def test_cables_join_two_owners_and_one_cable_per_port(client, db, admin_token):
    rack, server = await _rack_with_server(db)
    switch = (await client.post("/api/topology/rack-items", json=_item(rack.id, rack_unit=2, kind="switch_unmanaged", port_count=2), headers=HEADERS)).json()
    await client.put("/api/topology/ports", json={"owner_type": "device", "owner_id": server.id, "count": 2, "kind": "RJ45"}, headers=HEADERS)
    cabling = await _cabling(client)
    server_ports = sorted((p for p in cabling["ports"] if p["device_id"] == server.id), key=lambda p: p["number"])
    switch_ports = sorted((p for p in cabling["ports"] if p["rack_item_id"] == switch["id"]), key=lambda p: p["number"])

    same_port = await client.post("/api/topology/rack-cables", json={"a_port_id": server_ports[0]["id"], "b_port_id": server_ports[0]["id"]}, headers=HEADERS)
    assert same_port.status_code == 422

    same_owner = await client.post("/api/topology/rack-cables", json={"a_port_id": server_ports[0]["id"], "b_port_id": server_ports[1]["id"]}, headers=HEADERS)
    assert same_owner.status_code == 422

    made = await client.post(
        "/api/topology/rack-cables",
        json={"a_port_id": server_ports[0]["id"], "b_port_id": switch_ports[0]["id"], "cable": "OM4 LC-LC", "color": "#f5a524"},
        headers=HEADERS,
    )
    assert made.status_code == 200 and made.json()["cable"] == "OM4 LC-LC"

    reused = await client.post("/api/topology/rack-cables", json={"a_port_id": server_ports[0]["id"], "b_port_id": switch_ports[1]["id"]}, headers=HEADERS)
    assert reused.status_code == 409

    bad_colour = await client.patch(f"/api/topology/rack-cables/{made.json()['id']}", json={"color": "orange"}, headers=HEADERS)
    assert bad_colour.status_code == 422


@pytest.mark.asyncio
async def test_deleting_an_item_takes_its_ports_and_cables(client, db, admin_token):
    rack, server = await _rack_with_server(db)
    ups = (await client.post("/api/topology/rack-items", json=_item(rack.id, rack_unit=3, kind="ups", port_count=1), headers=HEADERS)).json()
    await client.put("/api/topology/ports", json={"owner_type": "device", "owner_id": server.id, "count": 1, "kind": "Power"}, headers=HEADERS)
    cabling = await _cabling(client)
    ups_port = next(p for p in cabling["ports"] if p["rack_item_id"] == ups["id"])
    server_port = next(p for p in cabling["ports"] if p["device_id"] == server.id)
    await client.post("/api/topology/rack-cables", json={"a_port_id": server_port["id"], "b_port_id": ups_port["id"], "cable": "Strom C13"}, headers=HEADERS)

    assert (await client.delete(f"/api/topology/rack-items/{ups['id']}", headers=HEADERS)).status_code == 200
    cabling = await _cabling(client)
    assert cabling["cables"] == []
    assert all(p["rack_item_id"] != ups["id"] for p in cabling["ports"])


@pytest.mark.asyncio
async def test_rack_size_follows_what_is_in_it(client, db, admin_token):
    rack, _ = await _rack_with_server(db)
    # The server sits on units 6 and 5: a 4-unit rack would lose it
    too_small = await client.patch(f"/api/topology/racks/{rack.id}", json={"units": 4}, headers=HEADERS)
    assert too_small.status_code == 409 and "pve-01" in too_small.json()["detail"]
    grown = await client.patch(f"/api/topology/racks/{rack.id}", json={"units": 24, "width": 10}, headers=HEADERS)
    assert grown.status_code == 200 and grown.json()["units"] == 24 and grown.json()["width"] == 10
    bad_width = await client.patch(f"/api/topology/racks/{rack.id}", json={"width": 7}, headers=HEADERS)
    assert bad_width.status_code == 422


@pytest.mark.asyncio
async def test_ports_have_a_side_for_front_and_rear_view(client, db, admin_token):
    rack, server = await _rack_with_server(db)
    rear = await client.put(
        "/api/topology/ports", json={"owner_type": "device", "owner_id": server.id, "count": 2, "kind": "RJ45", "side": "rear"}, headers=HEADERS
    )
    assert [p["side"] for p in rear.json()] == ["rear", "rear"]
    invalid = await client.put(
        "/api/topology/ports", json={"owner_type": "device", "owner_id": server.id, "count": 2, "kind": "RJ45", "side": "top"}, headers=HEADERS
    )
    assert invalid.status_code == 422
    item = (await client.post("/api/topology/rack-items", json=_item(rack.id, port_count=2), headers=HEADERS)).json()
    sides = [p["side"] for p in (await _cabling(client))["ports"] if p["rack_item_id"] == item["id"]]
    assert sides == ["front", "front"]


@pytest.mark.asyncio
async def test_power_strip_replaces_the_phone_system(client, db, admin_token):
    from app.database.migrations import _retire_phone_system_items
    from app.models.rack_cabling import RackItem

    rack, _ = await _rack_with_server(db)
    strip = await client.post("/api/topology/rack-items", json=_item(rack.id, kind="power_strip", port_count=8, port_kind="Power"), headers=HEADERS)
    assert strip.status_code == 200 and strip.json()["kind"] == "power_strip"
    # A phone system has an IP: it is a network device, not rack equipment
    phone = await client.post("/api/topology/rack-items", json=_item(rack.id, kind="phone_system", rack_unit=3), headers=HEADERS)
    assert phone.status_code == 422

    # Items of the old kind become "other" and keep their name
    old = RackItem(rack_id=rack.id, name="Telefonanlage", kind="phone_system", rack_unit=9, rack_height=1)
    db.add(old)
    await db.commit()
    await _retire_phone_system_items(db)
    await db.refresh(old)
    assert (old.kind, old.name) == ("other", "Telefonanlage")
