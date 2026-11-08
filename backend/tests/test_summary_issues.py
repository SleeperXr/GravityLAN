"""The summary and issues API (app/api/summary.py): device and agent counts, averages over the
active agents' latest metrics, scanner state and last scan time, and the issue list with filters."""

from datetime import datetime, timedelta, timezone

import pytest

import app.api.summary as summary
from app.models.agent import AgentToken, DeviceMetrics
from app.models.device import Device, Service
from app.schemas.scan import ScanProgress, ScanStatus


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def no_scan(monkeypatch):
    monkeypatch.setattr(summary.state, "last_progress", None)


@pytest.fixture
async def network(db):
    srv = Device(ip="192.0.2.10", hostname="srv", is_online=True, has_agent=True, last_seen=_now())
    nas = Device(ip="192.0.2.20", display_name="NAS", is_online=True, has_agent=True)
    cam = Device(ip="192.0.2.30", is_online=False, has_agent=True)
    db.add_all([srv, nas, cam])
    await db.flush()
    db.add_all([
        AgentToken(device_id=srv.id, token="sha256:" + "a" * 64, is_active=True, last_seen=_now()),
        AgentToken(device_id=nas.id, token="sha256:" + "b" * 64, is_active=True, last_seen=_now() - timedelta(hours=2)),
        # cam has_agent but no token at all
        DeviceMetrics(device_id=srv.id, timestamp=_now() - timedelta(minutes=2), cpu_percent=90.0, ram_percent=90.0),
        DeviceMetrics(device_id=srv.id, timestamp=_now(), cpu_percent=10.0, ram_percent=30.0),
        DeviceMetrics(device_id=nas.id, timestamp=_now(), cpu_percent=99.0, ram_percent=99.0),
        Service(device_id=nas.id, name="SMB", protocol="tcp", port=445, is_up=False),
        Service(device_id=srv.id, name="Web", protocol="http", port=80, is_up=True),
    ])
    await db.commit()
    return srv, nas, cam


async def test_summary_counts_averages_and_issues(client, auth, network, no_scan):
    body = (await client.get("/api/summary", headers=auth)).json()
    assert body["devices"] == {"total": 3, "online": 2, "offline": 1}
    # Only srv is active; its newest metrics count, not the older 90 %
    assert body["agents"] == {"total": 2, "active": 1, "avg_cpu": 10.0, "avg_ram": 30.0}
    assert body["scanner"]["status"] == "idle"
    assert body["scanner"]["last_scan"] is not None  # newest device last_seen
    issues = {(i["type"], i["device_name"]): i["details"] for i in body["active_issues"]}
    assert issues[("agent_offline", "NAS")].startswith("Agent has not reported since 20")
    assert issues[("agent_offline", "192.0.2.30")] == "Agent has not reported since never"
    assert issues[("service_down", "NAS")] == "Service SMB on port 445 is down"
    assert ("agent_offline", "srv") not in issues


async def test_summary_of_an_empty_install_uses_the_scan_state(client, auth, monkeypatch):
    progress = ScanProgress(status=ScanStatus.RUNNING, timestamp=datetime(2026, 11, 8, 12, 0))
    monkeypatch.setattr(summary.state, "last_progress", progress)
    body = (await client.get("/api/summary", headers=auth)).json()
    assert body["devices"] == {"total": 0, "online": 0, "offline": 0}
    assert body["agents"] == {"total": 0, "active": 0, "avg_cpu": 0.0, "avg_ram": 0.0}
    assert body["scanner"]["status"] == "running"
    assert body["scanner"]["last_scan"].startswith("2026-11-08T12:00:00")
    assert body["active_issues"] == []


async def test_active_agent_without_metrics_keeps_zero_averages(client, auth, db, no_scan):
    dev = Device(ip="192.0.2.40", is_online=True)
    db.add(dev)
    await db.flush()
    db.add(AgentToken(device_id=dev.id, token="sha256:" + "c" * 64, is_active=True, last_seen=_now()))
    await db.commit()
    body = (await client.get("/api/summary", headers=auth)).json()
    assert body["agents"] == {"total": 1, "active": 1, "avg_cpu": 0.0, "avg_ram": 0.0}


async def test_issue_filters(client, auth, network, no_scan):
    _srv, nas, _cam = network
    every = (await client.get("/api/issues", headers=auth)).json()
    assert len(every) == 3
    by_device = (await client.get(f"/api/issues?device_id={nas.id}", headers=auth)).json()
    assert {i["type"] for i in by_device} == {"agent_offline", "service_down"}
    by_type = (await client.get("/api/issues?type=service_down", headers=auth)).json()
    assert [i["device_name"] for i in by_type] == ["NAS"]
