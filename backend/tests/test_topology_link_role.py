"""Links carry a role: primary paths shape the map, backup paths only show redundancy."""

import pytest

from app.models.device import Device

HEADERS = {"Authorization": "Bearer test-admin-token-12345"}


async def _devices(db):
    a, b = Device(ip="10.0.0.1", display_name="a"), Device(ip="10.0.0.2", display_name="b")
    db.add_all([a, b])
    await db.commit()
    return a, b


@pytest.mark.asyncio
async def test_new_link_is_primary_and_can_become_backup(client, db, admin_token):
    a, b = await _devices(db)
    created = await client.post("/api/topology/links", json={"source_id": a.id, "target_id": b.id, "link_type": "Fiber"}, headers=HEADERS)
    assert created.status_code == 200
    assert created.json()["role"] == "primary"

    link_id = created.json()["id"]
    patched = await client.patch(f"/api/topology/links/{link_id}", json={"role": "backup"}, headers=HEADERS)
    assert patched.status_code == 200
    assert patched.json()["role"] == "backup"

    # null leaves the role alone instead of breaking the NOT NULL column
    kept = await client.patch(f"/api/topology/links/{link_id}", json={"role": None, "notes": "LACP standby"}, headers=HEADERS)
    assert kept.status_code == 200
    assert kept.json()["role"] == "backup" and kept.json()["notes"] == "LACP standby"


@pytest.mark.asyncio
async def test_unknown_role_is_rejected(client, db, admin_token):
    a, b = await _devices(db)
    response = await client.post("/api/topology/links", json={"source_id": a.id, "target_id": b.id, "role": "sometimes"}, headers=HEADERS)
    assert response.status_code == 422
