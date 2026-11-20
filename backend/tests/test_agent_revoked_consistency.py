"""Consistent handling of active, silent, pending, revoked, uninstalled and inconsistent agents.

Verifies the separated domain states across summary, issues, health, agent overview/status,
devices/groups endpoints, persistent token transitions, and the health probe:
1. Active reporting token (is_active=True, fresh last_seen)
2. Active silent token (is_active=True, stale/missing last_seen)
3. Active token with an additional pending_token (stays authorized, not downgraded to pending)
4. Pure pending adoption placeholder (is_active=False, pending_token set)
5. Revoked token (is_active=False, pending_token=None) with fresh historical DeviceMetrics
6. Uninstalled agent (remote uninstall mocked) with remaining historical DeviceMetrics
7. Pre-existing inconsistent DB row (Device.has_agent=True without an active AgentToken)
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.agent import AgentToken, DeviceMetrics
from app.models.device import Device, DeviceGroup, DeviceHealthSample, Service
from app.models.setting import Setting
from app.scanner.health_probe import run_health_probe_pass
from app.services.cache_service import dashboard_cache, topology_cache
from app.services.session_service import session_store


def _naive_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _clean_caches():
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()
    yield
    dashboard_cache.invalidate_all()
    topology_cache.invalidate()


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest_asyncio.fixture
async def session_cookies(db):
    db.add(Setting(key="setup.complete", value="true"))
    await db.commit()
    sid = session_store.create_session(user_agent="pytest")
    try:
        yield {"gravitylan_token": sid}
    finally:
        session_store.delete_session(sid)


async def _make_device(db, *, ip: str, name: str, has_agent: bool = False, group_id: int | None = None, now: datetime) -> Device:
    dev = Device(
        ip=ip,
        display_name=name,
        is_online=True,
        has_agent=has_agent,
        group_id=group_id,
        first_seen=_naive_utc(now - timedelta(days=1)),
        last_seen=_naive_utc(now),
    )
    db.add(dev)
    await db.flush()
    return dev


@pytest.mark.asyncio
async def test_revoked_agent_matches_no_agent_control_keeps_other_penalties_and_metrics(client, db, auth):
    """Revoked token with fresh metrics must not count as active/offline, must add zero extra
    health penalty vs an identical control device (even with a down service), and must keep
    historical metrics readable.
    """
    now = datetime.now(UTC)
    control = await _make_device(db, ip="192.0.2.10", name="control-srv", has_agent=False, now=now)
    revoked = await _make_device(db, ip="192.0.2.11", name="revoked-srv", has_agent=True, now=now)
    # Both devices share the exact same non-agent health defect (one down service)
    db.add_all([
        Service(device_id=control.id, name="Web", protocol="http", port=80, is_up=False),
        Service(device_id=revoked.id, name="Web", protocol="http", port=80, is_up=False),
        AgentToken(
            device_id=revoked.id, token="sha256:" + "a" * 64, is_active=False,
            last_seen=_naive_utc(now - timedelta(seconds=10)), agent_version="0.3.17",
        ),
        DeviceMetrics(
            device_id=revoked.id, cpu_percent=95.0, ram_used_mb=920, ram_total_mb=1024,
            ram_percent=90.0, temperature=85.0, timestamp=_naive_utc(now - timedelta(seconds=10)),
        ),
    ])
    await db.commit()

    summary = (await client.get("/api/summary", headers=auth)).json()
    assert summary["agents"] == {"total": 0, "active": 0, "avg_cpu": 0.0, "avg_ram": 0.0}
    assert {i["type"] for i in summary["active_issues"]} == {"service_down"}
    assert len(summary["active_issues"]) == 2

    hs = (await client.get("/api/health/summary", headers=auth)).json()
    assert hs["agents"] == {"total": 0, "high_cpu": 0, "high_temp": 0, "offline_agents": 0}
    assert hs["issues"]["by_type"] == {"agent_offline": 0, "service_down": 2}

    ho = {d["display_name"]: d for d in (await client.get("/api/health/overview?period=24h", headers=auth)).json()["devices"]}
    assert ho["revoked-srv"]["agent"] is None
    assert ho["revoked-srv"]["health_score"] < 100  # non-agent service_down penalty still applies
    assert ho["revoked-srv"]["health_score"] == ho["control-srv"]["health_score"]
    assert ho["revoked-srv"]["health_status"] == ho["control-srv"]["health_status"]

    hd_rev = (await client.get(f"/api/health/device/{revoked.id}?period=24h", headers=auth)).json()["device"]
    hd_ctl = (await client.get(f"/api/health/device/{control.id}?period=24h", headers=auth)).json()["device"]
    assert hd_rev["agent"] is None
    assert hd_rev["health_score"] == hd_ctl["health_score"]
    assert hd_rev["health_status"] == hd_ctl["health_status"]

    ao = (await client.get("/api/agent/overview", headers=auth)).json()
    assert (ao["total_agents"], ao["active_agents"], ao["agents"], ao["avg_cpu"], ao["avg_ram"]) == (0, 0, [], 0.0, 0.0)

    ast = (await client.get(f"/api/agent/status/{revoked.id}", headers=auth)).json()
    assert (ast["is_installed"], ast["is_active"], ast["is_healthy"]) == (False, False, False)

    devs = {d["id"]: d for d in (await client.get("/api/devices", headers=auth)).json()}
    dev_detail = (await client.get(f"/api/devices/{revoked.id}", headers=auth)).json()
    for view in (devs[revoked.id], dev_detail):
        assert view["has_agent"] is False
        assert view["has_pending_token"] is False
        assert view["agent_info"] is None

    # Historical metrics remain readable via metrics history endpoint
    metrics = (await client.get(f"/api/agent/metrics/{revoked.id}", headers=auth)).json()
    assert len(metrics["snapshots"]) == 1
    assert metrics["snapshots"][0]["cpu_percent"] == 95.0


@pytest.mark.asyncio
async def test_pure_pending_placeholder_stays_adoptable_without_counting_or_penalizing(client, db, auth):
    """Pure pending placeholder (is_active=False, pending_token set) stays visible on Agents
    overview for adoption, but is excluded from live counts, averages, issues and health penalties.
    """
    now = datetime.now(UTC)
    control = await _make_device(db, ip="192.0.2.12", name="control-pend", has_agent=False, now=now)
    pending = await _make_device(db, ip="192.0.2.13", name="pending-srv", has_agent=False, now=now)
    db.add_all([
        AgentToken(
            device_id=pending.id, token="sha256:" + "b" * 64, is_active=False,
            pending_token="sha256:" + "c" * 64, pending_at=_naive_utc(now), last_seen=None,
        ),
        # Stale historical metric from an earlier life must not leak into live overview averages
        DeviceMetrics(
            device_id=pending.id, cpu_percent=80.0, ram_used_mb=800, ram_total_mb=1000,
            ram_percent=80.0, timestamp=_naive_utc(now - timedelta(minutes=2)),
        ),
    ])
    await db.commit()

    summary = (await client.get("/api/summary", headers=auth)).json()
    assert summary["agents"] == {"total": 0, "active": 0, "avg_cpu": 0.0, "avg_ram": 0.0}
    assert summary["active_issues"] == []

    hs = (await client.get("/api/health/summary", headers=auth)).json()
    assert hs["agents"] == {"total": 0, "high_cpu": 0, "high_temp": 0, "offline_agents": 0}
    assert hs["issues"]["by_type"]["agent_offline"] == 0

    ho = {d["display_name"]: d for d in (await client.get("/api/health/overview?period=24h", headers=auth)).json()["devices"]}
    assert ho["pending-srv"]["agent"] is None
    assert ho["pending-srv"]["health_score"] == ho["control-pend"]["health_score"]
    assert ho["pending-srv"]["health_status"] == ho["control-pend"]["health_status"]

    hd_pend = (await client.get(f"/api/health/device/{pending.id}?period=24h", headers=auth)).json()["device"]
    hd_ctl = (await client.get(f"/api/health/device/{control.id}?period=24h", headers=auth)).json()["device"]
    assert hd_pend["agent"] is None
    assert hd_pend["health_score"] == hd_ctl["health_score"]

    # Visible on /api/agent/overview for adoption, excluded from live counters & averages
    ao = (await client.get("/api/agent/overview", headers=auth)).json()
    assert len(ao["agents"]) == 1
    assert ao["agents"][0]["device_id"] == pending.id
    assert ao["agents"][0]["has_pending_token"] is True
    assert ao["agents"][0]["is_online"] is False
    assert ao["agents"][0]["cpu_usage"] == 0.0
    assert ao["agents"][0]["uptime_history"] == []
    assert (ao["total_agents"], ao["active_agents"], ao["total_data_points"], ao["avg_cpu"], ao["avg_ram"]) == (0, 0, 0, 0.0, 0.0)

    ast = (await client.get(f"/api/agent/status/{pending.id}", headers=auth)).json()
    assert (ast["is_installed"], ast["is_active"], ast["is_healthy"]) == (False, False, False)

    devs = {d["id"]: d for d in (await client.get("/api/devices", headers=auth)).json()}
    dev_detail = (await client.get(f"/api/devices/{pending.id}", headers=auth)).json()
    for view in (devs[pending.id], dev_detail):
        assert view["has_agent"] is False
        assert view["has_pending_token"] is True
        assert view["agent_info"] is None


@pytest.mark.asyncio
async def test_active_token_with_pending_token_stays_authorized_and_not_downgraded(client, db, auth):
    """An active authorized agent that also received a mismatched pending_token must keep its
    active agent status across all endpoints while surfacing has_pending_token=True.
    """
    now = datetime.now(UTC)
    dev = await _make_device(db, ip="192.0.2.14", name="active-plus-pending", has_agent=True, now=now)
    db.add_all([
        AgentToken(
            device_id=dev.id, token="sha256:" + "d" * 64, is_active=True,
            pending_token="sha256:" + "e" * 64, pending_at=_naive_utc(now),
            last_seen=_naive_utc(now - timedelta(seconds=15)), agent_version="0.3.17",
        ),
        DeviceMetrics(
            device_id=dev.id, cpu_percent=30.0, ram_used_mb=400, ram_total_mb=1000,
            ram_percent=40.0, timestamp=_naive_utc(now - timedelta(seconds=15)),
        ),
    ])
    await db.commit()

    summary = (await client.get("/api/summary", headers=auth)).json()
    assert summary["agents"] == {"total": 1, "active": 1, "avg_cpu": 30.0, "avg_ram": 40.0}
    assert summary["active_issues"] == []

    ao = (await client.get("/api/agent/overview", headers=auth)).json()
    assert (ao["total_agents"], ao["active_agents"], ao["avg_cpu"], ao["avg_ram"]) == (1, 1, 30.0, 40.0)
    assert ao["agents"][0]["is_online"] is True
    assert ao["agents"][0]["has_pending_token"] is True

    ast = (await client.get(f"/api/agent/status/{dev.id}", headers=auth)).json()
    assert (ast["is_installed"], ast["is_active"], ast["is_healthy"]) == (True, True, True)

    devs = (await client.get("/api/devices", headers=auth)).json()
    dev_detail = (await client.get(f"/api/devices/{dev.id}", headers=auth)).json()
    for view in (devs[0], dev_detail):
        assert view["has_agent"] is True
        assert view["has_pending_token"] is True
        assert view["agent_info"] is not None
        assert view["agent_info"]["reporting"] is True


@pytest.mark.asyncio
async def test_uninstall_clears_has_agent_invalidates_caches_and_preserves_metrics(client, db, session_cookies):
    """Remote uninstall (mocked) removes AgentToken, resets Device.has_agent, invalidates caches,
    adds no health penalty vs control, and keeps historical DeviceMetrics readable.
    """
    now = datetime.now(UTC)
    await _make_device(db, ip="192.0.2.15", name="control-uninst", has_agent=False, now=now)
    dev = await _make_device(db, ip="192.0.2.16", name="uninstalled-srv", has_agent=True, now=now)
    db.add_all([
        AgentToken(
            device_id=dev.id, token="sha256:" + "1" * 64, is_active=True,
            last_seen=_naive_utc(now - timedelta(seconds=10)), agent_version="0.3.17",
        ),
        DeviceMetrics(
            device_id=dev.id, cpu_percent=42.0, ram_used_mb=256, ram_total_mb=1024,
            ram_percent=25.0, timestamp=_naive_utc(now - timedelta(seconds=10)),
        ),
    ])
    await db.commit()

    # Warm the device list cache before uninstall to prove invalidation works
    pre = {d["id"]: d for d in (await client.get("/api/devices", cookies=session_cookies)).json()}
    assert pre[dev.id]["has_agent"] is True

    with patch("app.api.agent.remove_agent", new=AsyncMock(return_value=(True, "removed"))):
        res = await client.post(
            f"/api/agent/uninstall/{dev.id}",
            json={"ssh_user": "root", "ssh_password": "secret", "ssh_port": 22},
            cookies=session_cookies,
        )
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    await db.refresh(dev)
    assert dev.has_agent is False
    assert (await db.execute(select(AgentToken).where(AgentToken.device_id == dev.id))).scalar_one_or_none() is None

    summary = (await client.get("/api/summary", cookies=session_cookies)).json()
    assert summary["agents"] == {"total": 0, "active": 0, "avg_cpu": 0.0, "avg_ram": 0.0}
    assert summary["active_issues"] == []

    ho = {d["display_name"]: d for d in (await client.get("/api/health/overview?period=24h", cookies=session_cookies)).json()["devices"]}
    assert ho["uninstalled-srv"]["agent"] is None
    assert ho["uninstalled-srv"]["health_score"] == ho["control-uninst"]["health_score"]
    assert ho["uninstalled-srv"]["health_status"] == ho["control-uninst"]["health_status"]

    # Without manual cache invalidation, /api/devices and /api/devices/{id} immediately agree
    post = {d["id"]: d for d in (await client.get("/api/devices", cookies=session_cookies)).json()}
    detail = (await client.get(f"/api/devices/{dev.id}", cookies=session_cookies)).json()
    for view in (post[dev.id], detail):
        assert view["has_agent"] is False
        assert view["agent_info"] is None

    metrics = (await client.get(f"/api/agent/metrics/{dev.id}", cookies=session_cookies)).json()
    assert len(metrics["snapshots"]) == 1
    assert metrics["snapshots"][0]["cpu_percent"] == 42.0


@pytest.mark.asyncio
async def test_existing_inconsistent_has_agent_row_renders_consistently_without_dirtying_session(client, db, auth):
    """Pre-existing inconsistent rows (Device.has_agent=True, no AgentToken) must render as
    having no agent across all read endpoints, AND pure GET reads must NOT dirty the ORM session
    or silently overwrite Device.has_agent on a subsequent commit.
    """
    now = datetime.now(UTC)
    group = DeviceGroup(name="Servers", icon="server", color="#3b82f6", sort_order=1)
    db.add(group)
    await db.flush()
    await _make_device(db, ip="192.0.2.17", name="control-inc", has_agent=False, group_id=group.id, now=now)
    ghost = await _make_device(db, ip="192.0.2.18", name="ghost-agent", has_agent=True, group_id=group.id, now=now)
    await db.commit()

    # Pure GET endpoints: list, detail, group detail
    devs = {d["id"]: d for d in (await client.get("/api/devices", headers=auth)).json()}
    detail = (await client.get(f"/api/devices/{ghost.id}", headers=auth)).json()
    group_detail = (await client.get(f"/api/groups/{group.id}", headers=auth)).json()
    group_by_id = {d["id"]: d for d in group_detail["devices"]}

    for view in (devs[ghost.id], detail, group_by_id[ghost.id]):
        assert view["has_agent"] is False
        assert view["has_pending_token"] is False
        assert view["agent_info"] is None

    # Critical Precision 2 check: read endpoints must never dirty ORM state or mutate DB column
    assert not db.dirty
    await db.commit()
    await db.refresh(ghost)
    assert ghost.has_agent is True

    # Summary & health also ignore the stale flag
    summary = (await client.get("/api/summary", headers=auth)).json()
    assert summary["agents"] == {"total": 0, "active": 0, "avg_cpu": 0.0, "avg_ram": 0.0}
    assert summary["active_issues"] == []

    ho = {d["display_name"]: d for d in (await client.get("/api/health/overview?period=24h", headers=auth)).json()["devices"]}
    assert ho["ghost-agent"]["agent"] is None
    assert ho["ghost-agent"]["health_score"] == ho["control-inc"]["health_score"]


@pytest.mark.asyncio
async def test_adoption_enrollment_and_deploy_transitions_keep_has_agent_in_sync(client, db, session_cookies):
    """Persistent token transitions (manual adoption, config enrollment, remote deploy) set
    Device.has_agent=True and invalidate device caches so subsequent reads reflect them immediately.
    """
    now = datetime.now(UTC)
    adopted_dev = await _make_device(db, ip="192.0.2.19", name="adopt-srv", has_agent=False, now=now)
    enrolled_dev = await _make_device(db, ip="192.0.2.20", name="enroll-srv", has_agent=False, now=now)
    deployed_dev = await _make_device(db, ip="192.0.2.21", name="deploy-srv", has_agent=False, now=now)
    db.add(AgentToken(
        device_id=adopted_dev.id, token="sha256:" + "2" * 64, is_active=False,
        pending_token="sha256:" + "3" * 64, pending_at=_naive_utc(now),
    ))
    await db.commit()

    # Warm cache before transitions
    pre = {d["id"]: d for d in (await client.get("/api/devices", cookies=session_cookies)).json()}
    assert pre[adopted_dev.id]["has_agent"] is False
    assert pre[adopted_dev.id]["has_pending_token"] is True

    # 1. Manual adoption
    res_adopt = await client.post(f"/api/agent/adopt/{adopted_dev.id}", cookies=session_cookies)
    assert res_adopt.status_code == 200
    await db.refresh(adopted_dev)
    assert adopted_dev.has_agent is True

    # 2. Enrollment config download via single-use install code
    enroll = await client.post(f"/api/agent/enroll/{enrolled_dev.id}", cookies=session_cookies)
    assert enroll.status_code == 200
    code = enroll.json()["code"]
    cfg = await client.get(f"/api/agent/download/config/{enrolled_dev.id}?code={code}")
    assert cfg.status_code == 200
    await db.refresh(enrolled_dev)
    assert enrolled_dev.has_agent is True

    # 3. Remote deploy (mocked)
    with patch("app.api.agent.deploy_agent", new=AsyncMock(return_value=(True, "deployed", "raw-new-token"))):
        res_deploy = await client.post(
            f"/api/agent/deploy/{deployed_dev.id}",
            json={"ssh_user": "root", "ssh_password": "secret", "ssh_port": 22},
            cookies=session_cookies,
        )
    assert res_deploy.status_code == 200
    assert res_deploy.json()["status"] == "success"
    await db.refresh(deployed_dev)
    assert deployed_dev.has_agent is True

    # All three are immediately reflected in cached /api/devices without manual cache clear
    post = {d["id"]: d for d in (await client.get("/api/devices", cookies=session_cookies)).json()}
    for dev in (adopted_dev, enrolled_dev, deployed_dev):
        assert post[dev.id]["has_agent"] is True
        assert post[dev.id]["has_pending_token"] is False


@pytest.mark.asyncio
async def test_active_reporting_and_silent_agents_keep_legitimate_behavior(client, db, auth):
    """Preservation test: active freshly reporting agents count as active/healthy, while active
    silent agents still trigger agent_offline and offline health status.
    """
    now = datetime.now(UTC)
    live = await _make_device(db, ip="192.0.2.25", name="live-srv", has_agent=True, now=now)
    silent = await _make_device(db, ip="192.0.2.26", name="silent-srv", has_agent=True, now=now)
    db.add_all([
        AgentToken(
            device_id=live.id, token="sha256:" + "e" * 64, is_active=True,
            last_seen=_naive_utc(now - timedelta(seconds=15)), agent_version="0.3.17",
        ),
        AgentToken(
            device_id=silent.id, token="sha256:" + "f" * 64, is_active=True,
            last_seen=_naive_utc(now - timedelta(hours=2)), agent_version="0.3.17",
        ),
        DeviceMetrics(
            device_id=live.id, cpu_percent=20.0, ram_used_mb=200, ram_total_mb=1000,
            ram_percent=20.0, timestamp=_naive_utc(now - timedelta(seconds=15)),
        ),
    ])
    await db.commit()

    summary = (await client.get("/api/summary", headers=auth)).json()
    assert summary["agents"] == {"total": 2, "active": 1, "avg_cpu": 20.0, "avg_ram": 20.0}
    assert [(i["type"], i["device_name"]) for i in summary["active_issues"]] == [("agent_offline", "silent-srv")]

    hs = (await client.get("/api/health/summary", headers=auth)).json()
    assert hs["agents"] == {"total": 2, "high_cpu": 0, "high_temp": 0, "offline_agents": 1}
    assert hs["issues"]["by_type"]["agent_offline"] == 1

    ho = {d["display_name"]: d for d in (await client.get("/api/health/overview?period=24h", headers=auth)).json()["devices"]}
    assert ho["live-srv"]["agent"]["is_active"] is True
    assert ho["live-srv"]["health_status"] == "healthy"
    assert ho["silent-srv"]["agent"]["is_active"] is False
    assert ho["silent-srv"]["health_status"] == "offline"

    detail_live = (await client.get(f"/api/devices/{live.id}", headers=auth)).json()
    detail_silent = (await client.get(f"/api/devices/{silent.id}", headers=auth)).json()
    assert detail_live["has_agent"] is True and detail_live["agent_info"]["reporting"] is True
    assert detail_silent["has_agent"] is True and detail_silent["agent_info"]["reporting"] is False


@pytest.mark.asyncio
async def test_health_probe_only_fast_offlines_active_silent_agents(db, monkeypatch):
    """Health probe fast-offline path must ignore revoked, pure pending, and inconsistent
    (has_agent=True without token) devices, while still fast-offlining active silent agents.
    """
    now = datetime.now(UTC)
    revoked = Device(ip="192.0.2.30", display_name="revoked", is_online=True, has_agent=True, missed_scans=0)
    pending = Device(ip="192.0.2.31", display_name="pending", is_online=True, has_agent=False, missed_scans=0)
    inconsistent = Device(ip="192.0.2.32", display_name="inconsistent", is_online=True, has_agent=True, missed_scans=0)
    active_silent = Device(ip="192.0.2.33", display_name="active-silent", is_online=True, has_agent=True, missed_scans=0)
    db.add_all([revoked, pending, inconsistent, active_silent])
    await db.flush()
    db.add_all([
        AgentToken(device_id=revoked.id, token="sha256:" + "1" * 64, is_active=False, last_seen=None),
        AgentToken(device_id=pending.id, token="sha256:" + "2" * 64, is_active=False, pending_token="sha256:" + "3" * 64, last_seen=None),
        AgentToken(device_id=active_silent.id, token="sha256:" + "4" * 64, is_active=True, last_seen=_naive_utc(now - timedelta(hours=1))),
    ])
    await db.commit()

    class _SessionCtx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    async def fake_probe(dev, ts, sem):
        return DeviceHealthSample(device_id=dev.id, timestamp=ts, is_online=False), {}

    monkeypatch.setattr("app.scanner.health_probe.async_session", lambda: _SessionCtx())
    monkeypatch.setattr("app.scanner.health_probe._probe_single_device", fake_probe)
    monkeypatch.setattr("app.scanner.health_probe.get_offline_threshold", AsyncMock(return_value=3))
    monkeypatch.setattr("app.scanner.health_probe.commit_or_discard", AsyncMock(return_value="ok"))

    await run_health_probe_pass()

    assert revoked.is_online is True and (revoked.missed_scans or 0) == 0
    assert pending.is_online is True and (pending.missed_scans or 0) == 0
    assert inconsistent.is_online is True and (inconsistent.missed_scans or 0) == 0
    assert active_silent.is_online is False


@pytest.mark.asyncio
async def test_live_averages_match_between_summary_and_agent_overview(client, db, auth):
    """Summary and /api/agent/overview must compute identical live CPU/RAM averages over
    currently reporting authorized agents with usable measurements only:
    - silent authorized agent with high old metric is excluded,
    - pure pending placeholder is excluded,
    - revoked agent with fresh historical metric is excluded,
    - reporting agent without any metric is not counted as 0,
    - a real measurement of 0.0 IS counted as valid.
    """
    now = datetime.now(UTC)
    live_measured = await _make_device(db, ip="192.0.2.40", name="live-measured", has_agent=True, now=now)
    live_no_metric = await _make_device(db, ip="192.0.2.41", name="live-no-metric", has_agent=True, now=now)
    silent_high = await _make_device(db, ip="192.0.2.42", name="silent-high", has_agent=True, now=now)
    pending_high = await _make_device(db, ip="192.0.2.43", name="pending-high", has_agent=False, now=now)
    revoked_high = await _make_device(db, ip="192.0.2.44", name="revoked-high", has_agent=True, now=now)
    db.add_all([
        AgentToken(
            device_id=live_measured.id, token="sha256:" + "a1" * 32, is_active=True,
            last_seen=_naive_utc(now - timedelta(seconds=10)), agent_version="0.3.17",
        ),
        AgentToken(
            device_id=live_no_metric.id, token="sha256:" + "a2" * 32, is_active=True,
            last_seen=_naive_utc(now - timedelta(seconds=10)), agent_version="0.3.17",
        ),
        AgentToken(
            device_id=silent_high.id, token="sha256:" + "a3" * 32, is_active=True,
            last_seen=_naive_utc(now - timedelta(hours=2)), agent_version="0.3.17",
        ),
        AgentToken(
            device_id=pending_high.id, token="sha256:" + "a4" * 32, is_active=False,
            pending_token="sha256:" + "a5" * 32, pending_at=_naive_utc(now), last_seen=None,
        ),
        AgentToken(
            device_id=revoked_high.id, token="sha256:" + "a6" * 32, is_active=False,
            last_seen=_naive_utc(now - timedelta(seconds=10)), agent_version="0.3.17",
        ),
        DeviceMetrics(
            device_id=live_measured.id, cpu_percent=40.0, ram_used_mb=600, ram_total_mb=1000,
            ram_percent=60.0, timestamp=_naive_utc(now - timedelta(seconds=10)),
        ),
        DeviceMetrics(
            device_id=silent_high.id, cpu_percent=99.0, ram_used_mb=980, ram_total_mb=1000,
            ram_percent=98.0, timestamp=_naive_utc(now - timedelta(hours=2)),
        ),
        DeviceMetrics(
            device_id=pending_high.id, cpu_percent=95.0, ram_used_mb=950, ram_total_mb=1000,
            ram_percent=95.0, timestamp=_naive_utc(now - timedelta(minutes=5)),
        ),
        DeviceMetrics(
            device_id=revoked_high.id, cpu_percent=97.0, ram_used_mb=970, ram_total_mb=1000,
            ram_percent=97.0, timestamp=_naive_utc(now - timedelta(seconds=10)),
        ),
    ])
    await db.commit()

    # Phase 1: live_no_metric has no DeviceMetrics -> must NOT dilute average as 0.0
    summary = (await client.get("/api/summary", headers=auth)).json()
    overview = (await client.get("/api/agent/overview", headers=auth)).json()

    assert summary["agents"] == {"total": 3, "active": 2, "avg_cpu": 40.0, "avg_ram": 60.0}
    assert (overview["total_agents"], overview["active_agents"], overview["avg_cpu"], overview["avg_ram"]) == (
        3, 2, 40.0, 60.0,
    )
    # Agents list holds the 3 authorized agents + 1 pending placeholder (revoked excluded)
    assert len(overview["agents"]) == 4

    # Phase 2: live_no_metric reports a genuine 0.0 measurement -> must count as valid (20.0 / 30.0)
    db.add(DeviceMetrics(
        device_id=live_no_metric.id, cpu_percent=0.0, ram_used_mb=0, ram_total_mb=1000,
        ram_percent=0.0, timestamp=_naive_utc(now - timedelta(seconds=5)),
    ))
    await db.commit()

    summary2 = (await client.get("/api/summary", headers=auth)).json()
    overview2 = (await client.get("/api/agent/overview", headers=auth)).json()

    assert summary2["agents"] == {"total": 3, "active": 2, "avg_cpu": 20.0, "avg_ram": 30.0}
    assert (overview2["total_agents"], overview2["active_agents"], overview2["avg_cpu"], overview2["avg_ram"]) == (
        3, 2, 20.0, 30.0,
    )
