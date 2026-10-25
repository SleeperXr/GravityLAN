"""Tests for backup cache invalidation and device group details batching (Befunde 4 & 5)."""

from datetime import datetime, timezone

import pytest

from app.api.agent import _latest_metrics
from app.api.auth import _setting_cache
from app.api.backup import invalidate_all_runtime_caches
from app.api.devices import dashboard_cache, get_group_details
from app.api.discovery import discovery_cache
from app.api.topology import topology_cache
from app.models.agent import AgentToken
from app.models.device import Device, DeviceGroup
from app.models.setting import Setting


def test_invalidate_all_runtime_caches_clears_populated_caches():
    """Befund 4: invalidate_all_runtime_caches must clear all in-memory caches."""
    # 1. Populate all in-memory runtime caches
    dashboard_cache["test_key"] = {"data": [1, 2, 3]}
    topology_cache["topology_key"] = {"nodes": ["a", "b"]}
    discovery_cache["discovery_key"] = {"hosts": ["192.168.1.1"]}
    _latest_metrics[42] = {"cpu_percent": 15.5}
    _setting_cache["test_setting"] = "cached_val"

    assert len(dashboard_cache) > 0
    assert len(topology_cache) > 0
    assert len(discovery_cache) > 0
    assert len(_latest_metrics) > 0
    assert len(_setting_cache) > 0

    # 2. Invoke cache invalidation
    invalidate_all_runtime_caches()

    # 3. Verify all caches are cleared
    assert len(dashboard_cache) == 0
    assert len(topology_cache) == 0
    assert len(discovery_cache) == 0
    assert len(_latest_metrics) == 0
    assert len(_setting_cache) == 0


@pytest.mark.asyncio
async def test_group_details_batch_loads_agent_tokens(db):
    """Befund 5: get_group_details batch loads AgentTokens instead of executing N+1 queries."""
    # 1. Setup group and devices
    group = DeviceGroup(id=1, name="Servers", is_default=False)
    db.add(group)
    await db.commit()

    dev1 = Device(id=101, ip="192.168.1.101", display_name="Web Server", group_id=1, is_online=True)
    dev2 = Device(id=102, ip="192.168.1.102", display_name="Printer", group_id=1, is_online=True)
    db.add_all([dev1, dev2])
    await db.commit()

    # dev1 has an active agent token; dev2 does not
    token1 = AgentToken(
        device_id=101,
        token="valid-token-hash-101",
        agent_version="v0.4.0",
        is_active=True,
    )
    db.add(token1)
    await db.commit()

    # 2. Fetch group details
    details = await get_group_details(group_id=1, db=db)

    assert details.id == 1
    assert details.device_count == 2
    assert len(details.devices) == 2

    # Map by id
    by_id = {d.id: d for d in details.devices}

    assert by_id[101].has_agent is True
    assert by_id[101].agent_info is not None
    assert by_id[101].agent_info.agent_version == "0.4.0"

    assert by_id[102].has_agent is False
    assert by_id[102].agent_info is None


@pytest.mark.asyncio
async def test_service_and_group_changes_clear_dashboard_cache(client, db, admin_token):
    from app.models.device import Device
    headers = {"Authorization": f"Bearer {admin_token}"}
    db.add(Device(id=1, ip="10.0.0.9"))
    await db.commit()

    def changed(response, status=200):
        assert response.status_code == status, response.text
        cleared = len(dashboard_cache) == 0
        dashboard_cache["list_devices:False:None"] = ["stale"]
        return cleared

    dashboard_cache["list_devices:False:None"] = ["stale"]
    svc = await client.post("/api/devices/1/services", json={"name": "Web", "port": 80, "protocol": "http"}, headers=headers)
    assert changed(svc)
    service_id = svc.json()["id"]
    assert changed(await client.patch(f"/api/services/{service_id}", json={"name": "Web UI"}, headers=headers))
    assert changed(await client.delete(f"/api/services/{service_id}", headers=headers), 204)
    group = await client.post("/api/groups", json={"name": "Lab"}, headers=headers)
    assert changed(group, 201)
    assert changed(await client.patch(f"/api/groups/{group.json()['id']}", json={"name": "Lab 2"}, headers=headers))
    assert changed(await client.delete(f"/api/groups/{group.json()['id']}", headers=headers), 204)



@pytest.mark.asyncio
async def test_reset_database_wipes_interfaces_caches_and_sessions(db, monkeypatch):
    """Befund 2: reset_database clears device_interfaces, runtime caches, and active browser sessions."""
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from app.api.settings import reset_database
    from app.models.device import DeviceInterface
    from app.scanner.scheduler import scheduler
    from app.services.session_service import session_store

    monkeypatch.setattr(scheduler, "stop", AsyncMock())
    monkeypatch.setattr(scheduler, "start", AsyncMock())

    dev = Device(id=601, ip="192.168.1.60", display_name="Router", is_online=True)
    db.add(dev)
    await db.commit()
    db.add(DeviceInterface(device_id=601, ip="192.168.110.1", label="VLAN 110"))
    await db.commit()

    dashboard_cache.set("list_devices:False:None", ["stale"])
    sid = session_store.create_session(user_agent="pytest")
    assert session_store.get_session(sid) is not None

    await reset_database(db=db)

    remaining_ifaces = (await db.execute(select(DeviceInterface))).scalars().all()
    assert remaining_ifaces == []
    assert dashboard_cache.get("list_devices:False:None") is None
    assert session_store.get_session(sid) is None
