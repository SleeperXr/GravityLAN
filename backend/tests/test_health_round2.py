"""app/api/health.py, second round: latency, uptime bars, overview KPIs and /summary keep their results.

Frozen copies (0.7.0-rc.7) of _latency_stats, _compute_uptime_and_latency and _overview_kpis run next to
the live functions over seeded random raw probes and rollup buckets; /summary is pinned with a database
scenario (hidden and placeholder devices, active, stale and disabled agents, hot metrics, issues, scanner).
"""

import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import app.api.health as health
from app.api.health import _compute_uptime_and_latency, _latency_stats, _overview_kpis
from app.schemas.health import (
    AgentHealthAlerts,
    DeviceHealthItem,
    HealthOverviewKPIs,
    LatencyStats,
    ServiceHealthItem,
    UptimeStats,
)
from app.scanner.utils import ensure_utc
from app.services.telemetry_query import HealthPoint


# --- frozen copies -------------------------------------------------------------------------

def _old_latency_stats(points):
    current_ms = None
    probe_type = None
    min_ms = avg_ms = max_ms = jitter_ms = None
    measured = [p for p in points if p.latency_count]
    if measured:
        min_ms = round(min(p.latency_min for p in measured if p.latency_min is not None), 1)
        max_ms = round(max(p.latency_max for p in measured if p.latency_max is not None), 1)
        total = sum(p.latency_count for p in measured)
        avg_ms = round(sum(p.latency_avg * p.latency_count for p in measured) / total, 1)
        jitter_sum = sum(p.jitter_sum for p in measured if not p.is_raw)
        jitter_count = sum(p.jitter_count for p in measured if not p.is_raw)
        raw_latencies = [p.latency_avg for p in measured if p.is_raw]
        for i in range(1, len(raw_latencies)):
            jitter_sum += abs(raw_latencies[i] - raw_latencies[i - 1])
            jitter_count += 1
        jitter_ms = round(jitter_sum / jitter_count, 1) if jitter_count else 0.0
    if points:
        last = points[-1]
        current_ms = last.latency_ms
        probe_type = last.probe_type
    sparkline = []
    if points:
        step = max(1, len(points) // 20)
        for i in range(0, len(points), step):
            sparkline.append(points[i].latency_ms)
        if len(sparkline) > 20:
            sparkline = sparkline[-20:]
    return LatencyStats(current_ms=current_ms, min_ms=min_ms, avg_ms=avg_ms, max_ms=max_ms,
                        jitter_ms=jitter_ms, sparkline=sparkline, probe_type=probe_type)


def _pct(online, samples):
    return round(online / samples * 100.0, 1)


def _old_uptime(dev, points, now, window_start, bucket_count):
    latency_stats = _old_latency_stats(points)
    total_seconds = (now - window_start).total_seconds()
    bucket_sec = total_seconds / bucket_count
    bars = [None] * bucket_count
    bucket_online = [0] * bucket_count
    bucket_samples = [0] * bucket_count
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    online_24h = total_24h = online_7d = total_7d = 0
    for p in points:
        p_time = ensure_utc(p.timestamp)
        if not p_time:
            continue
        if p_time >= cutoff_24h:
            total_24h += p.samples
            online_24h += p.online
        if p_time >= cutoff_7d:
            total_7d += p.samples
            online_7d += p.online
        idx = int((p_time - window_start).total_seconds() // bucket_sec)
        if 0 <= idx < bucket_count:
            bucket_online[idx] += p.online
            bucket_samples[idx] += p.samples
    for i in range(bucket_count):
        if bucket_samples[i]:
            bars[i] = _pct(bucket_online[i], bucket_samples[i])
        else:
            b_end = window_start + timedelta(seconds=(i + 1) * bucket_sec)
            dev_first_seen = ensure_utc(dev.first_seen) or now
            if dev_first_seen <= b_end:
                bars[i] = 100.0 if dev.is_online else 0.0
    total_samples = sum(p.samples for p in points)
    uptime_pct = _pct(sum(p.online for p in points), total_samples) if total_samples else (100.0 if dev.is_online else 0.0)
    uptime_24h = _pct(online_24h, total_24h) if total_24h else uptime_pct
    uptime_7d = _pct(online_7d, total_7d) if total_7d else uptime_pct
    return UptimeStats(uptime_pct=uptime_pct, uptime_24h=uptime_24h, uptime_7d=uptime_7d, uptime_30d=uptime_pct,
                       history_bars=bars), latency_stats


def _old_kpis(items):
    def mean(values):
        return round(sum(values) / len(values), 1) if values else None
    scores = [d.health_score for d in items]
    alerting = [d for d in items if getattr(d, "alert_offline", True)]
    return HealthOverviewKPIs(
        network_health_score=round(sum(scores) / len(scores)) if scores else 100,
        total_devices=len(items),
        online_devices=sum(1 for d in items if d.is_online and d.health_status != "offline"),
        offline_devices=sum(1 for d in alerting if not d.is_online or d.health_status == "offline"),
        flapping_devices=sum(1 for d in items if d.health_status == "flapping"),
        avg_latency_ms=mean([d.latency.avg_ms for d in items if d.latency.avg_ms is not None]),
        avg_jitter_ms=mean([d.latency.jitter_ms for d in items if d.latency.jitter_ms is not None]),
        active_issues_count=sum(1 for d in alerting if d.health_status in ("offline", "critical", "flapping")),
        ssl_warning_count=sum(1 for d in items for s in d.services
                              if not s.ignore_ssl and s.ssl_expiry_days is not None and s.ssl_expiry_days <= 14),
        patch_warning_count=sum(1 for d in items if d.agent and (d.agent.patch_security > 0 or d.agent.reboot_required)),
    )


# --- random inputs ---------------------------------------------------------------------------

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _points(rnd, window):
    points = []
    t = NOW - window - timedelta(hours=2)
    while t < NOW + timedelta(minutes=30):
        t += timedelta(minutes=rnd.choice([3, 17, 60, 240]))
        raw = rnd.random() < 0.6
        samples = 1 if raw else rnd.randint(1, 12)
        online = rnd.randint(0, samples)
        count = 0 if rnd.random() < 0.15 else (1 if raw else rnd.randint(1, samples))
        lat = round(rnd.uniform(0.3, 250), 2) if count else None
        stamp = t.replace(tzinfo=None) if rnd.random() < 0.5 else t
        points.append(HealthPoint(
            timestamp=stamp, samples=samples, online=online, latency_count=count,
            latency_min=(lat * 0.8 if lat and not raw else lat), latency_avg=lat,
            latency_max=(lat * 1.3 if lat and not raw else lat),
            jitter_sum=0.0 if raw else rnd.uniform(0, 30), jitter_count=0 if raw else rnd.randint(0, 5),
            probe_type=rnd.choice(["icmp", "tcp", None]), is_raw=raw,
        ))
    return points


@pytest.mark.parametrize("seed", range(150))
def test_latency_and_uptime_match_the_frozen_versions(seed):
    rnd = random.Random(seed)
    period, window, buckets = rnd.choice([("24h", timedelta(hours=24), 24), ("7d", timedelta(days=7), 28), ("30d", timedelta(days=30), 30)])
    points = _points(rnd, window) if rnd.random() < 0.9 else []
    first_seen = rnd.choice([None, NOW - timedelta(days=60), NOW - timedelta(hours=5), (NOW - timedelta(days=2)).replace(tzinfo=None)])
    dev = SimpleNamespace(first_seen=first_seen, is_online=rnd.random() < 0.7)
    window_start = NOW - window

    assert _latency_stats(points) == _old_latency_stats(points)
    assert _compute_uptime_and_latency(dev, points, NOW, window_start, buckets) == _old_uptime(dev, points, NOW, window_start, buckets)


def _item(rnd, i):
    agent = None
    if rnd.random() < 0.4:
        agent = AgentHealthAlerts(has_agent=True, is_active=rnd.random() < 0.7, patch_security=rnd.choice([0, 0, 2]),
                                  reboot_required=rnd.random() < 0.2)
    services = [ServiceHealthItem(id=j, name="s", protocol="https", port=443, is_up=rnd.random() < 0.8,
                                  ssl_expiry_days=rnd.choice([None, 3, 14, 15, 90]), ignore_ssl=rnd.random() < 0.2)
                for j in range(rnd.randint(0, 3))]
    return DeviceHealthItem(
        id=i, ip=f"10.0.0.{i}", display_name=f"d{i}", hostname=None, device_type="server", group_id=None, group_name=None,
        is_online=rnd.random() < 0.75, alert_offline=rnd.random() < 0.7, missed_scans=0,
        health_score=rnd.randint(0, 100), health_status=rnd.choice(["healthy", "degraded", "critical", "offline", "flapping", "standby"]),
        latency=LatencyStats(avg_ms=rnd.choice([None, 4.2, 80.0]), jitter_ms=rnd.choice([None, 0.0, 2.5])),
        uptime=UptimeStats(), services=services, agent=agent,
    )


@pytest.mark.parametrize("seed", range(100))
def test_overview_kpis_match_the_frozen_version(seed):
    rnd = random.Random(seed)
    items = [_item(rnd, i) for i in range(rnd.randint(0, 12))]
    assert _overview_kpis(items) == _old_kpis(items)


# --- /summary -------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summary_counts_devices_agents_issues_notifications_and_scanner(client, db, admin_token, monkeypatch):
    from app.models.agent import AgentToken, DeviceMetrics
    from app.models.device import Device, DeviceHistory

    now = datetime.now(UTC)
    naive = lambda dt: dt.replace(tzinfo=None)  # noqa: E731
    devs = [
        Device(ip="10.1.0.1", display_name="a", is_online=True),
        Device(ip="10.1.0.2", display_name="b", is_online=False),
        Device(ip="10.1.0.3", display_name="c", is_online=True),
        Device(ip="10.1.0.4", display_name="hidden", is_online=True, is_hidden=True),
        Device(ip="10.1.0.5", display_name="placeholder", is_online=False, ip_placeholder=True),
    ]
    db.add_all(devs)
    await db.flush()
    db.add_all([
        AgentToken(device_id=devs[0].id, token="t1", last_seen=naive(now - timedelta(seconds=20))),
        AgentToken(device_id=devs[2].id, token="t3", last_seen=naive(now - timedelta(seconds=30))),
        AgentToken(device_id=devs[1].id, token="t2", last_seen=naive(now - timedelta(hours=3))),
        AgentToken(device_id=devs[3].id, token="t4", last_seen=naive(now - timedelta(seconds=5)), is_active=False),
        DeviceMetrics(device_id=devs[0].id, cpu_percent=50.0, temperature=40.0, timestamp=naive(now - timedelta(minutes=5))),
        DeviceMetrics(device_id=devs[0].id, cpu_percent=95.0, temperature=80.0, timestamp=naive(now - timedelta(minutes=1))),
        DeviceMetrics(device_id=devs[2].id, cpu_percent=90.0, temperature=None, timestamp=naive(now)),
        DeviceMetrics(device_id=devs[1].id, cpu_percent=99.0, temperature=99.0, timestamp=naive(now)),
        DeviceHistory(device_id=devs[1].id, status="offline", message="x", timestamp=naive(now - timedelta(minutes=10))),
        DeviceHistory(device_id=devs[1].id, status="online", message="y", timestamp=naive(now - timedelta(hours=2))),
    ])
    await db.commit()

    last_scan = now - timedelta(hours=3, minutes=6)

    async def fake_summary(token, db):
        return SimpleNamespace(
            active_issues=[SimpleNamespace(type="service_down"), SimpleNamespace(type="service_down"), SimpleNamespace(type="ip_conflict")],
            scanner=SimpleNamespace(status="discovering", last_scan=last_scan),
        )

    monkeypatch.setattr(health, "get_summary", fake_summary)
    res = await client.get("/api/health/summary", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["devices"] == {"total": 3, "online": 2, "offline": 1}
    assert body["agents"] == {"total": 4, "high_cpu": 1, "high_temp": 1, "offline_agents": 2}
    assert body["issues"] == {"active": 3, "by_type": {"agent_offline": 0, "service_down": 2, "ip_conflict": 1}}
    assert body["notifications"] == {"unread": 2, "fresh_30min": 1}
    assert body["scanner"]["running"] is True
    assert body["scanner"]["stale_hours"] == 3.1


@pytest.mark.asyncio
async def test_summary_without_agents_or_scan(client, db, admin_token, monkeypatch):
    async def fake_summary(token, db):
        return SimpleNamespace(active_issues=[], scanner=SimpleNamespace(status="idle", last_scan=None))

    monkeypatch.setattr(health, "get_summary", fake_summary)
    body = (await client.get("/api/health/summary", headers={"Authorization": f"Bearer {admin_token}"})).json()
    assert body["agents"] == {"total": 0, "high_cpu": 0, "high_temp": 0, "offline_agents": 0}
    assert body["scanner"] == {"running": False, "last_run": None, "stale_hours": None}
    assert body["issues"] == {"active": 0, "by_type": {"agent_offline": 0, "service_down": 0}}


def test_parse_period_window_all_variants():
    from app.api.health import _parse_period_window

    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    start_7d, buckets_7d = _parse_period_window("7d", now)
    assert start_7d == now - timedelta(days=7)
    assert buckets_7d == 28

    start_30d, buckets_30d = _parse_period_window("30d", now)
    assert start_30d == now - timedelta(days=30)
    assert buckets_30d == 30

    start_24h, buckets_24h = _parse_period_window("24h", now)
    assert start_24h == now - timedelta(hours=24)
    assert buckets_24h == 24


def test_overview_incidents_caps_at_max():
    from app.api.health import MAX_OVERVIEW_INCIDENTS, _overview_incidents

    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    dev = SimpleNamespace(id=1, ip="10.0.0.1", display_name="dev1", name="dev1", alert_offline=True)
    rows = [
        (SimpleNamespace(id=i, status="offline", message=f"down {i}", timestamp=now), dev)
        for i in range(MAX_OVERVIEW_INCIDENTS + 10)
    ]
    incidents = _overview_incidents(rows, now)
    assert len(incidents) == MAX_OVERVIEW_INCIDENTS

