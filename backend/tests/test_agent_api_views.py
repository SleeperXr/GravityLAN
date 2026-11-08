"""The read and config endpoints of app/api/agent.py that the dashboard calls: per-device config
(created on first read, version bumped on change), the agents overview, global metrics, status,
metrics history ranges, the agent download and the uninstall script."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.agent import AgentConfig, AgentToken, DeviceMetrics
from app.models.device import Device


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
async def device(db):
    dev = Device(ip="192.0.2.20", hostname="nas", display_name="NAS")
    db.add(dev)
    await db.commit()
    return dev


# --- config ---------------------------------------------------------------------------------------

async def test_config_is_created_with_defaults_on_first_read(client, auth, device, db):
    res = await client.get(f"/api/agent/config/{device.id}", headers=auth)
    assert res.status_code == 200
    body = res.json()
    assert (body["interval"], body["disk_paths"], body["enable_temp"], body["enable_scanner_relay"]) == (30, ["/"], True, False)
    stored = (await db.execute(select(AgentConfig))).scalars().all()
    assert [c.device_id for c in stored] == [device.id]


async def test_config_update_changes_only_given_fields_and_bumps_the_version(client, auth, device, db):
    first = await client.patch(f"/api/agent/config/{device.id}", json={"interval": 60}, headers=auth)
    assert first.status_code == 200
    second = await client.patch(
        f"/api/agent/config/{device.id}",
        json={"disk_paths": ["/", "/mnt/data"], "enable_temp": False, "enable_patch_check": True, "enable_scanner_relay": True},
        headers=auth,
    )
    body = second.json()
    assert (body["interval"], body["disk_paths"], body["enable_temp"], body["enable_patch_check"], body["enable_scanner_relay"]) == (
        60, ["/", "/mnt/data"], False, True, True,
    )
    db.expire_all()
    config = (await db.execute(select(AgentConfig))).scalar_one()
    assert config.version == 3  # created at 1, two updates


# --- overview and global metrics --------------------------------------------------------------

async def test_overview_without_agents(client, auth):
    res = await client.get("/api/agent/overview", headers=auth)
    assert res.json() == {"agents": [], "total_agents": 0, "active_agents": 0, "total_data_points": 0, "avg_cpu": 0.0, "avg_ram": 0.0}


async def test_overview_and_global_metrics_with_one_agent(client, auth, device, db):
    db.add(AgentToken(device_id=device.id, token="sha256:" + "a" * 64, is_active=True, last_seen=_now(), agent_version="0.3.12"))
    db.add_all([
        DeviceMetrics(device_id=device.id, timestamp=_now() - timedelta(minutes=5), cpu_percent=20.0, ram_percent=40.0),
        DeviceMetrics(device_id=device.id, timestamp=_now() - timedelta(minutes=1), cpu_percent=30.0, ram_percent=50.0),
        DeviceMetrics(device_id=device.id, timestamp=_now() - timedelta(days=3), cpu_percent=99.0, ram_percent=99.0),
    ])
    await db.commit()

    overview = (await client.get("/api/agent/overview", headers=auth)).json()
    assert (overview["total_agents"], overview["active_agents"], overview["total_data_points"]) == (1, 1, 3)
    assert overview["agents"][0]["device_id"] == device.id

    res = await client.get("/api/agent/global-metrics", headers=auth)
    assert res.status_code == 200
    assert res.json()["history"]  # the two recent points land in a bucket; the 3-day-old one is outside the 24 h


# --- status ---------------------------------------------------------------------------------------

async def test_status_without_an_agent(client, auth, device):
    body = (await client.get(f"/api/agent/status/{device.id}", headers=auth)).json()
    assert (body["is_active"], body["message"]) == (False, "No agent linked")


async def test_status_of_a_recently_seen_agent(client, auth, device, db):
    db.add(AgentToken(device_id=device.id, token="sha256:" + "b" * 64, is_active=True, last_seen=_now(), agent_version="0.3.12"))
    db.add(DeviceMetrics(device_id=device.id, timestamp=_now(), cpu_percent=12.0, ram_percent=34.0))
    await db.commit()
    body = (await client.get(f"/api/agent/status/{device.id}", headers=auth)).json()
    assert (body["is_installed"], body["is_active"], body["is_healthy"]) == (True, True, True)
    assert body["latest_metrics"]["cpu_percent"] == 12.0


async def test_status_of_an_agent_not_seen_for_an_hour(client, auth, device, db):
    db.add(AgentToken(device_id=device.id, token="sha256:" + "c" * 64, is_active=True, last_seen=_now() - timedelta(hours=1)))
    await db.commit()
    body = (await client.get(f"/api/agent/status/{device.id}", headers=auth)).json()
    assert (body["is_active"], body["is_healthy"], body["latest_metrics"]) == (False, False, None)


# --- metrics history --------------------------------------------------------------------------

async def test_metrics_history_latest_points_in_order(client, auth, device, db):
    db.add_all([DeviceMetrics(device_id=device.id, timestamp=_now() - timedelta(minutes=m), cpu_percent=float(m), ram_percent=1.0) for m in (3, 2, 1)])
    await db.commit()
    body = (await client.get(f"/api/agent/metrics/{device.id}?limit=2", headers=auth)).json()
    assert [s["cpu_percent"] for s in body["snapshots"]] == [2.0, 1.0]
    assert body["available_ranges"][0] == "6h"


async def test_metrics_history_rejects_an_unknown_range(client, auth, device):
    res = await client.get(f"/api/agent/metrics/{device.id}?range=1y", headers=auth)
    assert res.status_code == 400
    assert "Valid ranges are: 6h, 24h, 7d, 30d" in res.json()["detail"]


@pytest.mark.parametrize("window", ["6h", "24h", "7d", "30d"])
async def test_metrics_history_ranges(client, auth, device, db, window):
    db.add(DeviceMetrics(device_id=device.id, timestamp=_now() - timedelta(minutes=10), cpu_percent=5.0, ram_percent=6.0))
    await db.commit()
    res = await client.get(f"/api/agent/metrics/{device.id}?range={window}", headers=auth)
    assert res.status_code == 200
    assert res.json()["device_id"] == device.id


# --- downloads ----------------------------------------------------------------------------------

async def test_agent_download_and_missing_script(client, monkeypatch, tmp_path):
    script = tmp_path / "gravitylan-agent.py"
    script.write_text("print('agent')")
    monkeypatch.setattr("app.services.agent_deployer.AGENT_SCRIPT_PATH", script)
    ok = await client.get("/api/agent/download/agent")
    assert ok.status_code == 200 and "agent" in ok.text

    monkeypatch.setattr("app.services.agent_deployer.AGENT_SCRIPT_PATH", tmp_path / "missing.py")
    assert (await client.get("/api/agent/download/agent")).status_code == 404


async def test_uninstall_script_needs_a_known_device(client, device):
    ok = await client.get(f"/api/agent/download/uninstall-sh/{device.id}")
    assert ok.status_code == 200 and ok.text.startswith("#!")
    assert (await client.get("/api/agent/download/uninstall-sh/9999")).status_code == 404
