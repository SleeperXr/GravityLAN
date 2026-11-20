"""Regression tests for Finding F: historical measurement gaps and availability semantics (H1, A1, U2, W2)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.api.health import _calculate_health_score, _compute_uptime_and_latency
from app.models.agent import AgentToken
from app.models.device import Device, DeviceHealthSample
from app.models.setting import Setting
from app.models.telemetry import HOUR, DeviceHealthRollup
from app.scanner.health_probe import run_health_probe_pass
from app.schemas.health import LatencyStats, ServiceHealthItem, UptimeStats
from app.services import telemetry_rollups as rollups
from app.services.agent_telemetry import _compute_uptime_history, _compute_uptime_pct


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# 1. No probes in entire period & new device (H1 + U2)
# ---------------------------------------------------------------------------

def test_no_probes_in_entire_window_and_new_device_yield_none():
    """A device without probes (new or unmeasured) has None for all uptime percentages and bars."""
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    window_start = now - timedelta(hours=24)

    for is_online in (True, False):
        for first_seen in (now, now - timedelta(days=30), None):
            dev = SimpleNamespace(first_seen=first_seen, is_online=is_online, alert_offline=True, missed_scans=0)
            uptime, latency = _compute_uptime_and_latency(dev, [], now, window_start, 24)
            assert uptime.uptime_pct is None
            assert uptime.uptime_24h is None
            assert uptime.uptime_7d is None
            assert uptime.uptime_30d is None
            assert uptime.history_bars == [None] * 24
            assert latency.current_ms is None
            assert latency.avg_ms is None


def test_health_score_does_not_penalize_missing_uptime_data_but_keeps_other_penalties():
    """UptimeStats(uptime_pct=None) adds 0 uptime penalty while offline state and other penalties remain active."""
    online_dev = SimpleNamespace(alert_offline=True, is_online=True, missed_scans=0)
    assert _calculate_health_score(online_dev, UptimeStats(uptime_pct=None), LatencyStats(), [], None) == (100, "healthy")

    # Offline state still yields 0 / offline
    offline_dev = SimpleNamespace(alert_offline=True, is_online=False, missed_scans=3)
    assert _calculate_health_score(offline_dev, UptimeStats(uptime_pct=None), LatencyStats(), [], None) == (0, "offline")

    # Missed scans (-15) and downed service (-20) still apply when uptime_pct is None
    flapping_dev = SimpleNamespace(alert_offline=True, is_online=True, missed_scans=1)
    down_svc = ServiceHealthItem(id=1, name="HTTP", protocol="http", port=80, is_up=False)
    score, status = _calculate_health_score(
        flapping_dev, UptimeStats(uptime_pct=None), LatencyStats(avg_ms=10.0), [down_svc], None
    )
    assert score == 65
    assert status == "flapping"


# ---------------------------------------------------------------------------
# 2. Measurement gaps & 3. Status invariance of historical bars (H1)
# ---------------------------------------------------------------------------

def test_measurement_gaps_between_probes_and_invariance_under_current_status_change():
    """Gaps between probes remain None and historical values do not flip when dev.is_online changes."""
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    window_start = now - timedelta(hours=24)

    # Probes only in bucket 2 (all online -> 100%), bucket 10 (1 online, 1 offline -> 50%),
    # and bucket 20 (all offline -> 0%). All other 21 buckets have no probes.
    samples = [
        SimpleNamespace(timestamp=_naive(window_start + timedelta(hours=2, minutes=10)), is_online=True, latency_ms=4.0),
        SimpleNamespace(timestamp=_naive(window_start + timedelta(hours=10, minutes=10)), is_online=True, latency_ms=6.0),
        SimpleNamespace(timestamp=_naive(window_start + timedelta(hours=10, minutes=20)), is_online=False, latency_ms=None),
        SimpleNamespace(timestamp=_naive(window_start + timedelta(hours=20, minutes=15)), is_online=False, latency_ms=None),
    ]

    dev_online = SimpleNamespace(first_seen=now - timedelta(days=90), is_online=True)
    dev_offline = SimpleNamespace(first_seen=now - timedelta(days=90), is_online=False)

    uptime_when_online, lat_on = _compute_uptime_and_latency(dev_online, samples, now, window_start, 24)
    uptime_when_offline, lat_off = _compute_uptime_and_latency(dev_offline, samples, now, window_start, 24)

    # Changing current dev.is_online must not alter historical uptime or bars
    assert uptime_when_online == uptime_when_offline
    assert lat_on == lat_off

    bars = uptime_when_online.history_bars
    assert len(bars) == 24
    assert bars[2] == 100.0
    assert bars[10] == 50.0
    assert bars[20] == 0.0  # Real 0 % vs None
    for idx in range(24):
        if idx not in (2, 10, 20):
            assert bars[idx] is None, f"Bucket {idx} without probes must be None, got {bars[idx]}"

    # Overall: 2 online out of 4 probes = 50.0 %
    assert uptime_when_online.uptime_pct == 50.0


# ---------------------------------------------------------------------------
# 4. True 0 % vs None & 5. Probes in 30d but none in 24h (U2 + W2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_true_zero_percent_vs_null_and_30d_probes_without_24h_probes(client, db, admin_token):
    """True 0 % (failed probes) is preserved as 0.0, while a window with zero probes returns None."""
    now = datetime.now(UTC)
    dev_down = Device(ip="192.0.2.101", display_name="Measured-Down", is_online=False)
    dev_unmeasured = Device(ip="192.0.2.102", display_name="Unmeasured", is_online=False)
    dev_old_only = Device(ip="192.0.2.103", display_name="Old-Probes-Only", is_online=True)
    db.add_all([dev_down, dev_unmeasured, dev_old_only])
    await db.flush()

    # dev_down has failed probes in the last hour -> real 0.0 %
    db.add_all([
        DeviceHealthSample(device_id=dev_down.id, timestamp=_naive(now - timedelta(minutes=30)), is_online=False, latency_ms=None),
        DeviceHealthSample(device_id=dev_down.id, timestamp=_naive(now - timedelta(minutes=15)), is_online=False, latency_ms=None),
    ])

    # dev_old_only has probes 10 days ago (in 30d), but zero in 7d and zero in 24h
    db.add_all([
        DeviceHealthSample(device_id=dev_old_only.id, timestamp=_naive(now - timedelta(days=10, hours=2)), is_online=True, latency_ms=3.0),
        DeviceHealthSample(device_id=dev_old_only.id, timestamp=_naive(now - timedelta(days=10, hours=1)), is_online=True, latency_ms=4.0),
    ])
    await db.commit()

    headers = {"Authorization": f"Bearer {admin_token}"}
    res = await client.get("/api/health/overview?period=24h", headers=headers)
    assert res.status_code == 200
    by_name = {d["display_name"]: d for d in res.json()["devices"]}

    # Measured failed probes -> 0.0 %
    u_down = by_name["Measured-Down"]["uptime"]
    assert u_down["uptime_pct"] == 0.0
    assert u_down["uptime_24h"] == 0.0
    assert u_down["uptime_7d"] == 0.0
    assert u_down["uptime_30d"] == 0.0
    assert u_down["history_bars"][-1] == 0.0
    assert all(b is None for b in u_down["history_bars"][:-1])

    # Zero probes -> None
    u_unm = by_name["Unmeasured"]["uptime"]
    assert u_unm["uptime_pct"] is None
    assert u_unm["uptime_24h"] is None
    assert u_unm["uptime_7d"] is None
    assert u_unm["uptime_30d"] is None
    assert u_unm["history_bars"] == [None] * 24

    # Probes only in 30d -> uptime_24h is None, uptime_7d is None, uptime_30d is 100.0
    u_old = by_name["Old-Probes-Only"]["uptime"]
    assert u_old["uptime_pct"] is None
    assert u_old["uptime_24h"] is None
    assert u_old["uptime_7d"] is None
    assert u_old["uptime_30d"] == 100.0
    assert u_old["history_bars"] == [None] * 24


# ---------------------------------------------------------------------------
# 6. Distinct 24h / 7d / 30d values across all period selections & 12. Rollups (W2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_window_uptimes_stay_consistent_across_period_selections_with_rollups(client, db, admin_token):
    """uptime_24h, uptime_7d and uptime_30d return their true window values across period=24h, 7d and 30d."""
    now = datetime.now(UTC).replace(minute=30, second=0, microsecond=0)
    naive_now = _naive(now)
    dev = Device(ip="192.0.2.110", display_name="Multi-Window-Host", is_online=True)
    db.add(dev)
    await db.flush()

    # 1. Within 24h (2 hours ago): 4 probes, 4 online -> 24h uptime = 100.0 %
    for m in (10, 20, 30, 40):
        db.add(DeviceHealthSample(
            device_id=dev.id, timestamp=naive_now - timedelta(hours=2, minutes=m), is_online=True, latency_ms=2.0
        ))

    # 2. Between 24h and 7d (3 days ago): 4 probes, 0 online -> 7d total: 4/8 online = 50.0 %
    for m in (10, 20, 30, 40):
        db.add(DeviceHealthSample(
            device_id=dev.id, timestamp=naive_now - timedelta(days=3, minutes=m), is_online=False, latency_ms=None
        ))

    # 3. Between 7d and 30d (15 days ago): 8 probes, 0 online -> 30d total: 4/16 online = 25.0 %
    for m in (5, 10, 15, 20, 25, 30, 35, 40):
        db.add(DeviceHealthSample(
            device_id=dev.id, timestamp=naive_now - timedelta(days=15, minutes=m), is_online=False, latency_ms=None
        ))

    db.add(Setting(key="telemetry.raw_retention_hours", value="24"))
    await db.commit()
    await rollups.run_telemetry_maintenance(db, naive_now)

    headers = {"Authorization": f"Bearer {admin_token}"}
    expected_period_pct = {"24h": 100.0, "7d": 50.0, "30d": 25.0}
    expected_bars_len = {"24h": 24, "7d": 28, "30d": 30}

    for period in ("24h", "7d", "30d"):
        ov = (await client.get(f"/api/health/overview?period={period}", headers=headers)).json()
        item = next(d for d in ov["devices"] if d["id"] == dev.id)
        u = item["uptime"]
        assert u["uptime_24h"] == 100.0, f"period={period}"
        assert u["uptime_7d"] == 50.0, f"period={period}"
        assert u["uptime_30d"] == 25.0, f"period={period}"
        assert u["uptime_pct"] == expected_period_pct[period], f"period={period}"
        assert len(u["history_bars"]) == expected_bars_len[period], f"period={period}"

        det = (await client.get(f"/api/health/device/{dev.id}?period={period}", headers=headers)).json()
        du = det["device"]["uptime"]
        assert du == u


@pytest.mark.asyncio
async def test_rollup_bucket_straddling_window_boundary_is_not_falsely_attributed(db):
    """A rollup bucket whose bucket_start is older than window_start is excluded from the newer window."""
    from app.services.telemetry_query import load_health_window_uptimes

    # Set now to 14:30 UTC so 7d ago is 14:30 UTC (mid-hour)
    now = datetime(2026, 11, 20, 14, 30, 0)
    seven_days_ago = now - timedelta(days=7)  # 2026-11-13 14:30:00
    straddling_hour_start = datetime(2026, 11, 13, 14, 0, 0)  # [14:00, 15:00) straddles 14:30
    inside_hour_start = datetime(2026, 11, 13, 15, 0, 0)      # [15:00, 16:00) is strictly inside 7d

    dev = Device(ip="192.0.2.115", display_name="Boundary-Host", is_online=True)
    db.add(dev)
    await db.flush()

    # Straddling bucket [14:00, 15:00) has 10 offline probes (0% online)
    db.add(DeviceHealthRollup(
        device_id=dev.id, resolution=HOUR, bucket_start=straddling_hour_start,
        samples=10, online=0, latency_count=0,
    ))
    # Inside bucket [15:00, 16:00) has 10 online probes (100% online)
    db.add(DeviceHealthRollup(
        device_id=dev.id, resolution=HOUR, bucket_start=inside_hour_start,
        samples=10, online=10, latency_count=10, latency_min=2.0, latency_avg=2.0, latency_max=2.0,
    ))
    await db.commit()

    assert straddling_hour_start < seven_days_ago < (straddling_hour_start + timedelta(hours=1))
    uptimes = await load_health_window_uptimes(db, [dev.id], now)
    # 7d window excludes the straddling [14:00, 15:00) bucket (100.0 %), while 30d includes both (50.0 %)
    assert uptimes[dev.id]["24h"] is None
    assert uptimes[dev.id]["7d"] == 100.0
    assert uptimes[dev.id]["30d"] == 50.0


# ---------------------------------------------------------------------------
# 8, 9, 10. Agent report coverage: pre-registration, partial first hour, running hour, empty bucket (A1)
# ---------------------------------------------------------------------------

def test_agent_report_coverage_pre_registration_and_partial_first_hour():
    """Hours before token.created_at are None; a mid-hour registration scales expected reports to end - start."""
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)
    cutoff_24h = now - timedelta(hours=24)
    # Token registered 1.5 hours ago (at 10:30 UTC, halfway through bucket 22 [10:00, 11:00))
    registered_at = now - timedelta(hours=1, minutes=30)
    token = SimpleNamespace(created_at=_naive(registered_at))

    # In bucket 22 [10:00, 11:00), only [10:30, 11:00) (1800s) is observed -> at 30s interval, expected = 60.
    # Send 30 reports in [10:30, 11:00) -> 50.0 % coverage for bucket 22.
    # In bucket 23 [11:00, 12:00) (3600s), expected = 120. Send 120 reports -> 100.0 % coverage.
    reports = [
        SimpleNamespace(timestamp=_naive(registered_at + timedelta(seconds=30 * i)))
        for i in range(30)
    ] + [
        SimpleNamespace(timestamp=_naive(now - timedelta(hours=1) + timedelta(seconds=30 * i)))
        for i in range(120)
    ]

    history = _compute_uptime_history(token, now, cutoff_24h, reports, interval=30)
    assert len(history) == 24
    assert history[:22] == [None] * 22
    assert history[22] == pytest.approx(50.0)
    assert history[23] == pytest.approx(100.0)

    # Overall 24h report coverage: 150 reports in 1.5h (5400s -> expected 180) = 83.333... %
    pct = _compute_uptime_pct(token, now, cutoff_24h, reports, interval=30)
    assert pct == pytest.approx(150 / 180 * 100.0)


def test_agent_running_hour_counts_only_up_to_now_and_empty_buckets_are_none():
    """A bucket extending past now is clipped to now; an observed hour with 0 reports returns None."""
    # Suppose cutoff_24h is aligned to full hours so bucket 23 starts 20 minutes before now and ends 40 minutes after now
    now = datetime(2026, 11, 20, 12, 20, 0, tzinfo=UTC)
    cutoff_24h = datetime(2026, 11, 19, 13, 0, 0, tzinfo=UTC)
    token = SimpleNamespace(created_at=_naive(now - timedelta(days=5)))

    # Bucket 22 is [11:00, 12:00) -> 0 reports (measurement-free bucket within runtime -> None)
    # Bucket 23 is [12:00, 13:00), clipped at now=12:20 -> 20 minutes elapsed (1200s -> expected 40 at 30s interval)
    reports = [
        SimpleNamespace(timestamp=_naive(datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=30 * i)))
        for i in range(40)
    ]

    history = _compute_uptime_history(token, now, cutoff_24h, reports, interval=30)
    assert history[22] is None  # Measurement-free bucket is None, not 0.0
    assert history[23] == pytest.approx(100.0)  # Running hour clipped at now


@pytest.mark.asyncio
async def test_silent_agent_without_24h_reports_yields_null_coverage_while_keeping_staleness_alert(client, db, admin_token):
    """An authorized agent with zero reports in 24h has uptime_pct=None and all-None history, while still flagged offline."""
    now = datetime.now(UTC)
    dev = Device(ip="192.0.2.140", display_name="Silent-Agent-Host", is_online=True, has_agent=True)
    db.add(dev)
    await db.flush()
    db.add(AgentToken(
        device_id=dev.id,
        token="sha256:" + "a" * 64,
        is_active=True,
        created_at=_naive(now - timedelta(days=5)),
        last_seen=_naive(now - timedelta(days=2)),
        agent_version="0.3.17",
    ))
    await db.commit()

    headers = {"Authorization": f"Bearer {admin_token}"}
    ao = (await client.get("/api/agent/overview", headers=headers)).json()
    agent_row = next(a for a in ao["agents"] if a["device_id"] == dev.id)
    assert agent_row["is_online"] is False
    assert agent_row["uptime_pct"] is None
    assert agent_row["uptime_history"] == [None] * 24

    summary = (await client.get("/api/summary", headers=headers)).json()
    assert any(i["type"] == "agent_offline" and i["device_id"] == dev.id for i in summary["active_issues"])


# ---------------------------------------------------------------------------
# 11. Health probes paused by open MAC conflict produce None in bucket (AP 3 + Befund F)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_probes_paused_by_mac_conflict_produce_null_bucket(monkeypatch, db):
    """When an open MAC conflict pauses L3 health probes, the unprobed bucket is None rather than 100 % or 0 %."""
    from contextlib import asynccontextmanager
    from app.scanner import health_probe as hp_mod

    @asynccontextmanager
    async def fake_session():
        yield db

    monkeypatch.setattr(hp_mod, "async_session", fake_session)

    now = datetime.now(UTC)
    dev = Device(
        ip="192.0.2.150",
        mac="AA:BB:CC:DD:EE:01",
        display_name="Conflict-Paused",
        is_online=True,
        first_seen=_naive(now - timedelta(days=10)),
    )
    db.add(dev)
    await db.flush()

    # Historical probe 3 hours ago (before the conflict)
    db.add(DeviceHealthSample(
        device_id=dev.id, timestamp=_naive(now - timedelta(hours=3, minutes=30)), is_online=True, latency_ms=2.5
    ))
    # Open MAC conflict at the device's current IP and MAC
    from app.services import mac_observations
    await mac_observations.record_mac_conflict(db, dev, "AA:BB:CC:DD:EE:99", source="scan")
    await db.commit()

    # Probe pass skips the device due to the open MAC conflict
    sampled = await run_health_probe_pass()
    assert sampled == 0

    rows = (await db.execute(select(DeviceHealthSample).where(DeviceHealthSample.device_id == dev.id))).scalars().all()
    assert len(rows) == 1

    uptime, _ = _compute_uptime_and_latency(dev, rows, now, now - timedelta(hours=24), 24)
    # Only the bucket 3 hours ago has a measurement; the current bucket (and all conflict-paused buckets) are None
    assert uptime.history_bars[-1] is None
    assert sum(1 for b in uptime.history_bars if b is not None) == 1
    assert uptime.uptime_pct == 100.0
