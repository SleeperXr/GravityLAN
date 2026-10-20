"""Telemetry database: rollups, window selection, legacy move, device deletion, purge API."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from app.models.agent import DeviceMetrics
from app.models.device import Device, DeviceHealthSample
from app.models.setting import Setting
from app.models.telemetry import DAY, HOUR, DeviceHealthRollup, DeviceMetricsRollup
from app.services import telemetry_rollups as rollups
from app.services.telemetry_query import (
    RAW,
    Segment,
    choose_resolution,
    load_health_points,
    load_metric_points,
    plan_segments,
)
from app.services.telemetry_store import (
    TelemetryRetention,
    delete_device_telemetry,
    migrate_legacy_telemetry,
)

# A fixed "now" keeps the hour/day boundaries deterministic
NOW = datetime(2026, 10, 20, 12, 30)


async def _device(db, ip="10.0.0.5") -> Device:
    dev = Device(ip=ip, display_name=ip, is_online=True, first_seen=NOW - timedelta(days=60))
    db.add(dev)
    await db.commit()
    return dev


def _sample(dev_id, ts, online=True, latency=2.0, ports_up=1, ports_total=1):
    return DeviceHealthSample(
        device_id=dev_id, timestamp=ts, is_online=online,
        latency_ms=latency if online else None, probe_type="icmp" if online else None,
        ports_up=ports_up if online else 0, ports_total=ports_total,
    )


def _metric(dev_id, ts, cpu, temp=None, rx=0, tx=0, disk=40.0):
    return DeviceMetrics(
        device_id=dev_id, timestamp=ts, cpu_percent=cpu, ram_percent=cpu / 2,
        ram_used_mb=1000, ram_total_mb=4000, temperature=temp,
        disk_json=json.dumps([{"path": "/", "total_gb": 100.0, "used_gb": disk, "percent": disk}]),
        net_json=json.dumps({"eth0": {"rx_bytes_sec": rx, "tx_bytes_sec": tx}}),
    )


# --- raw -> hourly -----------------------------------------------------------

async def test_health_hour_rollup_aggregates_and_is_idempotent(db):
    dev = await _device(db)
    hour = datetime(2026, 10, 20, 9, 0)
    # 4 probes: 3 online (latency 1, 3, 2), 1 offline
    db.add_all([
        _sample(dev.id, hour + timedelta(minutes=1), latency=1.0),
        _sample(dev.id, hour + timedelta(minutes=2), latency=3.0),
        _sample(dev.id, hour + timedelta(minutes=3), online=False),
        _sample(dev.id, hour + timedelta(minutes=4), latency=2.0),
    ])
    await db.commit()

    assert await rollups.rollup_health_hours(db, NOW) == 1
    r = (await db.execute(select(DeviceHealthRollup))).scalar_one()
    assert (r.resolution, r.bucket_start) == (HOUR, hour)
    assert (r.samples, r.online, r.latency_count) == (4, 3, 3)
    assert (r.latency_min, r.latency_max) == (1.0, 3.0)
    assert r.latency_avg == pytest.approx(2.0)
    # consecutive latency differences: |3-1| + |2-3| over 2 pairs
    assert (r.jitter_sum, r.jitter_count) == (pytest.approx(3.0), 2)
    assert r.ports_up_avg == pytest.approx(0.75)

    # A second run finds nothing new
    assert await rollups.rollup_health_hours(db, NOW) == 0


async def test_hour_rollup_skips_current_hour_and_gaps(db):
    dev = await _device(db)
    db.add_all([
        _sample(dev.id, datetime(2026, 10, 18, 3, 10)),   # two days back
        _sample(dev.id, datetime(2026, 10, 20, 11, 59)),  # last complete hour
        _sample(dev.id, datetime(2026, 10, 20, 12, 5)),   # current hour: not rolled up
    ])
    await db.commit()

    assert await rollups.rollup_health_hours(db, NOW) == 2
    buckets = (await db.execute(
        select(DeviceHealthRollup.bucket_start).order_by(DeviceHealthRollup.bucket_start)
    )).scalars().all()
    assert buckets == [datetime(2026, 10, 18, 3), datetime(2026, 10, 20, 11)]


async def test_metrics_hour_rollup(db):
    dev = await _device(db)
    hour = datetime(2026, 10, 20, 10, 0)
    db.add_all([
        _metric(dev.id, hour + timedelta(minutes=1), cpu=10.0, temp=40.0, rx=100, tx=10, disk=40.0),
        _metric(dev.id, hour + timedelta(minutes=2), cpu=30.0, temp=None, rx=300, tx=30, disk=55.0),
    ])
    await db.commit()

    assert await rollups.rollup_metrics_hours(db, NOW) == 1
    r = (await db.execute(select(DeviceMetricsRollup))).scalar_one()
    assert r.samples == 2
    assert (r.cpu_avg, r.cpu_max) == (pytest.approx(20.0), 30.0)
    assert (r.temp_count, r.temp_avg, r.temp_max) == (1, 40.0, 40.0)
    assert (r.net_rx_avg, r.net_rx_max, r.net_tx_max) == (pytest.approx(200.0), 300.0, 30.0)
    assert r.disk_percent_max == 55.0
    assert json.loads(r.disk_json)[0]["percent"] == 55.0  # last snapshot of the hour


# --- hourly -> daily ---------------------------------------------------------

async def test_daily_rollup_weights_hours(db):
    dev = await _device(db)
    day = datetime(2026, 10, 18)
    db.add_all([
        DeviceHealthRollup(device_id=dev.id, resolution=HOUR, bucket_start=day + timedelta(hours=1),
                           samples=60, online=60, latency_count=60, latency_min=1.0, latency_avg=2.0,
                           latency_max=4.0, jitter_sum=30.0, jitter_count=59, ports_up_avg=1.0, ports_total=1),
        DeviceHealthRollup(device_id=dev.id, resolution=HOUR, bucket_start=day + timedelta(hours=2),
                           samples=20, online=0, latency_count=0, ports_up_avg=0.0, ports_total=1),
    ])
    await db.commit()

    assert await rollups.rollup_health_days(db, NOW) == 1
    d = (await db.execute(select(DeviceHealthRollup).where(DeviceHealthRollup.resolution == DAY))).scalar_one()
    assert d.bucket_start == day
    assert (d.samples, d.online, d.latency_count) == (80, 60, 60)
    assert d.latency_avg == pytest.approx(2.0)
    assert d.ports_up_avg == pytest.approx(0.75)
    assert (d.jitter_sum, d.jitter_count) == (30.0, 59)
    # The 19th has no hourly rows and the 20th is not complete yet: nothing more
    assert await rollups.rollup_health_days(db, NOW) == 0


# --- pruning ------------------------------------------------------------------

async def test_prune_keeps_raw_rows_that_are_not_rolled_up(db):
    dev = await _device(db)
    db.add(_sample(dev.id, NOW - timedelta(days=5)))
    await db.commit()

    retention = TelemetryRetention(raw_hours=24, hourly_days=30, daily_days=365)
    # Without any hourly rollup the raw row must survive, whatever its age
    deleted = await rollups.prune_telemetry(db, NOW, retention)
    assert deleted["health_raw"] == 0
    assert (await db.execute(select(func.count()).select_from(DeviceHealthSample))).scalar() == 1

    stats = await rollups.run_telemetry_maintenance(db, NOW)
    assert stats["health_hourly_added"] == 1
    assert (await db.execute(select(func.count()).select_from(DeviceHealthSample))).scalar() == 0
    assert (await db.execute(select(func.count()).select_from(DeviceHealthRollup))).scalar() == 2  # hour + day


async def test_maintenance_applies_retention_settings(db):
    dev = await _device(db)
    db.add(Setting(key="telemetry.raw_retention_hours", value="24"))
    db.add(Setting(key="telemetry.hourly_retention_days", value="2"))
    db.add(Setting(key="telemetry.daily_retention_days", value="7"))
    db.add_all([_sample(dev.id, NOW - timedelta(days=d, minutes=5)) for d in (0, 1, 3, 10)])
    await db.commit()

    await rollups.run_telemetry_maintenance(db, NOW)
    raw = (await db.execute(select(DeviceHealthSample.timestamp))).scalars().all()
    assert raw and all(ts >= NOW - timedelta(hours=25) for ts in raw)
    hourly = (await db.execute(
        select(DeviceHealthRollup.bucket_start).where(DeviceHealthRollup.resolution == HOUR)
    )).scalars().all()
    assert all(ts >= NOW - timedelta(days=3) for ts in hourly)
    daily = (await db.execute(
        select(DeviceHealthRollup.bucket_start).where(DeviceHealthRollup.resolution == DAY)
    )).scalars().all()
    assert daily and all(ts >= NOW - timedelta(days=8) for ts in daily)


# --- window selection -----------------------------------------------------------

def test_choose_resolution():
    r = TelemetryRetention(raw_hours=48, hourly_days=30, daily_days=365)
    assert choose_resolution(timedelta(hours=24), r) == RAW
    assert choose_resolution(timedelta(days=7), r) == HOUR
    assert choose_resolution(timedelta(days=30), r) == HOUR
    assert choose_resolution(timedelta(days=90), r) == DAY


def test_plan_segments_hourly_then_raw_for_the_newest_hour():
    ws = NOW - timedelta(days=7)
    coverage = {
        RAW: (NOW - timedelta(hours=48), datetime.max),
        HOUR: (NOW - timedelta(days=20), datetime(2026, 10, 20, 11)),
        DAY: None,
    }
    segs = plan_segments(ws, HOUR, coverage)
    assert [(s.tier, s.start, s.end) for s in segs] == [
        (HOUR, ws, datetime(2026, 10, 20, 11)),
        (RAW, datetime(2026, 10, 20, 11), None),
    ]


def test_plan_segments_fills_older_part_from_coarser_tier():
    ws = NOW - timedelta(days=30)
    coverage = {
        RAW: (datetime(2026, 10, 18, 12, 10), datetime.max),
        HOUR: (datetime(2026, 10, 6), datetime(2026, 10, 20, 11)),
        DAY: (datetime(2026, 1, 1), datetime(2026, 10, 20)),
    }
    segs = plan_segments(ws, HOUR, coverage)
    assert [(s.tier, s.start, s.end) for s in segs] == [
        (DAY, ws, datetime(2026, 10, 6)),
        (HOUR, datetime(2026, 10, 6), datetime(2026, 10, 20, 11)),
        (RAW, datetime(2026, 10, 20, 11), None),
    ]


def test_plan_segments_does_not_fill_where_the_recording_began():
    # Data started on the 14th at 19:00: the daily rollup of that day holds the same
    # hours, so the window starts with the hourly tier instead of a misplaced day point
    ws = NOW - timedelta(days=30)
    coverage = {
        RAW: (datetime(2026, 10, 18, 13), datetime.max),
        HOUR: (datetime(2026, 10, 14, 19), datetime(2026, 10, 20, 11)),
        DAY: (datetime(2026, 10, 14), datetime(2026, 10, 20)),
    }
    segs = plan_segments(ws, HOUR, coverage)
    assert [(s.tier, s.start, s.end) for s in segs] == [
        (HOUR, ws, datetime(2026, 10, 20, 11)),
        (RAW, datetime(2026, 10, 20, 11), None),
    ]


def test_plan_segments_raw_window_without_rollups():
    ws = NOW - timedelta(hours=24)
    segs = plan_segments(ws, RAW, {RAW: (NOW - timedelta(hours=3), datetime.max), HOUR: None, DAY: None})
    assert segs == [Segment(RAW, ws, None)]


async def test_load_health_points_stitches_without_double_counting(db):
    dev = await _device(db)
    # Probes every 10 minutes for 3 days; the device is offline on the oldest day
    ts = NOW - timedelta(days=3)
    while ts < NOW:
        db.add(_sample(dev.id, ts, online=ts >= NOW - timedelta(days=2)))
        ts += timedelta(minutes=10)
    db.add(Setting(key="telemetry.raw_retention_hours", value="24"))
    await db.commit()
    total = (await db.execute(select(func.count()).select_from(DeviceHealthSample))).scalar()
    online = (await db.execute(
        select(func.count()).select_from(DeviceHealthSample).where(DeviceHealthSample.is_online)
    )).scalar()

    # Hourly rollups for everything complete, raw pruned to 24 h
    await rollups.run_telemetry_maintenance(db, NOW)
    assert (await db.execute(select(func.min(DeviceHealthSample.timestamp)))).scalar() >= NOW - timedelta(hours=25)

    points = (await load_health_points(db, [dev.id], NOW - timedelta(days=7), NOW))[dev.id]
    assert sum(p.samples for p in points) == total
    assert sum(p.online for p in points) == online
    assert not points[0].is_raw and points[-1].is_raw


async def test_load_metric_points_uses_rollups_for_long_ranges(db):
    dev = await _device(db)
    db.add_all([_metric(dev.id, NOW - timedelta(hours=h, minutes=1), cpu=float(h % 10)) for h in range(72)])
    await db.commit()
    await rollups.run_telemetry_maintenance(db, NOW)

    points = await load_metric_points(db, dev.id, NOW - timedelta(days=7), NOW)
    assert sum(p.samples for p in points) == 72
    assert not points[0].is_raw


# --- legacy move -------------------------------------------------------------------

async def test_migrate_legacy_tables_from_inventory(db):
    dev = await _device(db)
    # Tables as an older version left them in the inventory file
    await db.execute(text(
        "CREATE TABLE main.device_health_samples (id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, "
        "timestamp DATETIME, is_online BOOLEAN NOT NULL, latency_ms FLOAT, probe_type VARCHAR(8), "
        "ports_up INTEGER NOT NULL, ports_total INTEGER NOT NULL)"
    ))
    await db.execute(text(
        "CREATE TABLE main.device_metrics (id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL, "
        "cpu_percent FLOAT NOT NULL, ram_used_mb INTEGER NOT NULL, ram_total_mb INTEGER NOT NULL, "
        "ram_percent FLOAT NOT NULL, disk_json TEXT, temperature FLOAT, net_json TEXT, timestamp DATETIME, "
        "patch_available INTEGER DEFAULT 0, patch_security INTEGER DEFAULT 0, patch_manager VARCHAR(20), "
        "reboot_required BOOLEAN DEFAULT FALSE, major_upgrade_available VARCHAR(100))"
    ))
    await db.execute(text(
        "INSERT INTO main.device_health_samples VALUES (7, :d, '2026-10-19 10:00:00.000000', 1, 1.5, 'icmp', 1, 1)"
    ), {"d": dev.id})
    await db.execute(text(
        "INSERT INTO main.device_metrics (id, device_id, cpu_percent, ram_used_mb, ram_total_mb, ram_percent, timestamp) "
        "VALUES (9, :d, 12.5, 100, 200, 50.0, '2026-10-19 10:00:00.000000')"
    ), {"d": dev.id})
    await db.commit()

    assert await migrate_legacy_telemetry(db) == 2
    left = (await db.execute(text(
        "SELECT name FROM main.sqlite_master WHERE name IN ('device_metrics', 'device_health_samples')"
    ))).all()
    assert left == []
    sample = (await db.execute(select(DeviceHealthSample))).scalar_one()
    assert (sample.id, sample.latency_ms, sample.timestamp) == (7, 1.5, datetime(2026, 10, 19, 10))
    metric = (await db.execute(select(DeviceMetrics))).scalar_one()
    assert (metric.id, metric.cpu_percent, metric.patch_available) == (9, 12.5, 0)

    # Repeatable: nothing left to move
    assert await migrate_legacy_telemetry(db) == 0


async def test_migrate_legacy_is_safe_after_an_interrupted_copy(db):
    dev = await _device(db)
    db.add(_sample(dev.id, datetime(2026, 10, 19, 10)))
    await db.commit()
    sample_id = (await db.execute(select(DeviceHealthSample.id))).scalar_one()
    # The copy happened, the DROP did not: the same row is in both files
    await db.execute(text(
        "CREATE TABLE main.device_health_samples AS SELECT * FROM telemetry.device_health_samples"
    ))
    await db.commit()

    assert await migrate_legacy_telemetry(db) == 0
    assert (await db.execute(select(DeviceHealthSample.id))).scalars().all() == [sample_id]


# --- device deletion ------------------------------------------------------------------

async def _seed_telemetry(db, dev_id):
    db.add(_sample(dev_id, NOW - timedelta(minutes=5)))
    db.add(_metric(dev_id, NOW - timedelta(minutes=5), cpu=1.0))
    db.add(DeviceHealthRollup(device_id=dev_id, resolution=HOUR, bucket_start=datetime(2026, 10, 19), samples=1, online=1))
    db.add(DeviceMetricsRollup(device_id=dev_id, resolution=DAY, bucket_start=datetime(2026, 10, 18), samples=1))
    await db.commit()


async def _telemetry_rows(db, dev_id) -> int:
    total = 0
    for model in (DeviceHealthSample, DeviceMetrics, DeviceHealthRollup, DeviceMetricsRollup):
        total += (await db.execute(
            select(func.count()).select_from(model).where(model.device_id == dev_id)
        )).scalar()
    return total


async def test_delete_device_removes_its_telemetry(client, db, admin_token):
    keep = await _device(db, ip="10.0.0.6")
    gone = await _device(db, ip="10.0.0.7")
    await _seed_telemetry(db, keep.id)
    await _seed_telemetry(db, gone.id)

    res = await client.delete(f"/api/devices/{gone.id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 204
    assert await _telemetry_rows(db, gone.id) == 0
    assert await _telemetry_rows(db, keep.id) == 4


async def test_bulk_delete_removes_telemetry(client, db, admin_token):
    a = await _device(db, ip="10.0.0.10")
    b = await _device(db, ip="10.0.0.11")
    await _seed_telemetry(db, a.id)
    await _seed_telemetry(db, b.id)

    res = await client.post("/api/devices/bulk-delete", json=[a.id, b.id],
                            headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 204
    assert await _telemetry_rows(db, a.id) + await _telemetry_rows(db, b.id) == 0


async def test_delete_device_telemetry_helper(db):
    dev = await _device(db)
    await _seed_telemetry(db, dev.id)
    assert await delete_device_telemetry(db, [dev.id]) == 4
    await db.commit()
    assert await _telemetry_rows(db, dev.id) == 0


# --- Settings > Measurement data API --------------------------------------------------

async def test_status_endpoint(client, db, admin_token):
    dev = await _device(db)
    await _seed_telemetry(db, dev.id)
    res = await client.get("/api/settings/telemetry", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["retention"] == {"raw_hours": 48, "hourly_days": 30, "daily_days": 365}
    assert data["tables"]["device_health_samples"]["rows"] == 1
    assert data["tables"]["device_metrics_rollups"]["rows"] == 1
    assert set(data["sizes"]) == {"inventory_bytes", "telemetry_bytes", "telemetry_free_bytes"}
    assert data["sizes"]["inventory_bytes"] > 0 and data["sizes"]["telemetry_bytes"] > 0
    assert data["limits"]["raw_hours"]["min"] == 24


async def test_update_retention_validates(client, db, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    ok = await client.put("/api/settings/telemetry/retention", headers=headers,
                          json={"raw_hours": 72, "hourly_days": 14, "daily_days": 180})
    assert ok.status_code == 200
    assert ok.json()["retention"] == {"raw_hours": 72, "hourly_days": 14, "daily_days": 180}

    too_short = await client.put("/api/settings/telemetry/retention", headers=headers,
                                 json={"raw_hours": 12, "hourly_days": 14, "daily_days": 180})
    assert too_short.status_code == 422
    not_nested = await client.put("/api/settings/telemetry/retention", headers=headers,
                                  json={"raw_hours": 48, "hourly_days": 60, "daily_days": 30})
    assert not_nested.status_code == 422


async def test_purge_older_than(client, db, admin_token):
    dev = await _device(db)
    now = datetime.now(UTC).replace(tzinfo=None)
    db.add(_sample(dev.id, now - timedelta(minutes=5)))
    db.add(DeviceHealthRollup(device_id=dev.id, resolution=DAY, bucket_start=now - timedelta(days=40), samples=1, online=1))
    await db.commit()

    res = await client.post("/api/settings/telemetry/purge", headers={"Authorization": f"Bearer {admin_token}"},
                            json={"scope": "older_than", "older_than_days": 30})
    assert res.status_code == 200
    assert res.json()["deleted"]["device_health_rollups"] == 1
    assert res.json()["deleted"]["device_health_samples"] == 0
    assert (await db.execute(select(func.count()).select_from(DeviceHealthSample))).scalar() == 1


async def test_purge_device_and_all(client, db, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    a = await _device(db, ip="10.0.0.8")
    b = await _device(db, ip="10.0.0.9")
    await _seed_telemetry(db, a.id)
    await _seed_telemetry(db, b.id)

    res = await client.post("/api/settings/telemetry/purge", headers=headers, json={"scope": "device", "device_id": a.id})
    assert res.status_code == 200
    assert await _telemetry_rows(db, a.id) == 0
    assert await _telemetry_rows(db, b.id) == 4

    missing = await client.post("/api/settings/telemetry/purge", headers=headers, json={"scope": "device", "device_id": 999})
    assert missing.status_code == 404
    no_days = await client.post("/api/settings/telemetry/purge", headers=headers, json={"scope": "older_than"})
    assert no_days.status_code == 422

    res = await client.post("/api/settings/telemetry/purge", headers=headers, json={"scope": "all"})
    assert res.status_code == 200
    assert await _telemetry_rows(db, b.id) == 0
    # Freed pages went back (incremental vacuum), none are left on the freelist
    assert res.json()["sizes"]["telemetry_free_bytes"] == 0
    # The inventory is untouched
    assert (await db.execute(select(func.count()).select_from(Device))).scalar() == 2


async def _api_token(client, admin_token, scopes) -> str:
    res = await client.post("/api/auth/tokens", headers={"Authorization": f"Bearer {admin_token}"},
                            json={"name": "automation", "scopes": scopes})
    assert res.status_code == 200
    return res.json()["token"]


async def test_purge_requires_settings_write_scope(client, db, admin_token):
    reader = await _api_token(client, admin_token, ["settings:read"])
    headers = {"Authorization": f"Bearer {reader}"}
    assert (await client.get("/api/settings/telemetry", headers=headers)).status_code == 200
    purge = await client.post("/api/settings/telemetry/purge", headers=headers, json={"scope": "all"})
    assert purge.status_code == 403
    retention = await client.put("/api/settings/telemetry/retention", headers=headers,
                                 json={"raw_hours": 48, "hourly_days": 30, "daily_days": 365})
    assert retention.status_code == 403

    writer = await _api_token(client, admin_token, ["settings:read", "settings:write"])
    res = await client.post("/api/settings/telemetry/purge", headers={"Authorization": f"Bearer {writer}"},
                            json={"scope": "all"})
    assert res.status_code == 200


async def test_endpoints_require_login(client, db, admin_token):
    assert (await client.get("/api/settings/telemetry")).status_code == 401
    assert (await client.post("/api/settings/telemetry/purge", json={"scope": "all"})).status_code == 401


# --- Health and agent APIs on rolled-up data ---------------------------------------------

async def test_health_overview_7d_reads_rollups_after_raw_pruning(client, db, admin_token):
    dev = await _device(db)
    now = datetime.now(UTC).replace(tzinfo=None)
    # 4 days of probes every 30 minutes, offline for the oldest day
    ts = now - timedelta(days=4)
    while ts < now:
        db.add(_sample(dev.id, ts, online=ts >= now - timedelta(days=3), latency=5.0))
        ts += timedelta(minutes=30)
    db.add(Setting(key="telemetry.raw_retention_hours", value="24"))
    await db.commit()
    await rollups.run_telemetry_maintenance(db, now)
    assert (await db.execute(select(func.min(DeviceHealthSample.timestamp)))).scalar() > now - timedelta(days=2)

    headers = {"Authorization": f"Bearer {admin_token}"}
    res = await client.get("/api/health/overview?period=7d", headers=headers)
    assert res.status_code == 200
    item = next(d for d in res.json()["devices"] if d["id"] == dev.id)
    # A quarter of the probes were offline although the raw rows of that day are gone
    assert item["uptime"]["uptime_pct"] == pytest.approx(75.0, abs=1.0)
    assert item["latency"]["avg_ms"] == 5.0
    assert item["latency"]["jitter_ms"] == 0.0

    detail = await client.get(f"/api/health/device/{dev.id}?period=7d", headers=headers)
    assert detail.status_code == 200
    series = detail.json()["time_series"]
    assert series and all("uptime_pct" in p for p in series)


async def test_agent_metrics_30d_range_reads_rollups(client, db, admin_token):
    dev = await _device(db)
    now = datetime.now(UTC).replace(tzinfo=None)
    db.add_all([_metric(dev.id, now - timedelta(hours=h, minutes=1), cpu=50.0) for h in range(0, 24 * 5, 2)])
    db.add(Setting(key="telemetry.raw_retention_hours", value="24"))
    await db.commit()
    await rollups.run_telemetry_maintenance(db, now)

    res = await client.get(f"/api/agent/metrics/{dev.id}?range=30d", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    snapshots = res.json()["snapshots"]
    # 60 reports over 5 days in 6-hour buckets, every one at 50 % CPU
    assert len(snapshots) >= 18
    assert all(s["cpu_percent"] == pytest.approx(50.0) for s in snapshots)
