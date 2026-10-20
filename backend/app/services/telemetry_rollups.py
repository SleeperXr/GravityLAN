"""Fold raw measurements into hourly and daily rollups and prune each tier.

``run_telemetry_maintenance`` runs hourly from the scheduler's retention loop (and
once right after startup, which also covers data written by older versions):

1. every complete hour that has raw rows but no hourly rollup yet becomes one
   DeviceHealthRollup / DeviceMetricsRollup row per device,
2. every complete day with hourly rollups becomes one daily row per device,
3. each tier is pruned to its retention, never past what the next coarser tier
   already holds, and the freed space goes back to the file system.

Progress is tracked by the newest rollup per resolution, so an interrupted run
continues where it stopped and a repeated run adds nothing twice.
"""

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import DeviceMetrics
from app.models.device import DeviceHealthSample
from app.models.telemetry import DAY, HOUR, DeviceHealthRollup, DeviceMetricsRollup
from app.services.telemetry_store import TelemetryRetention, get_retention, reclaim_telemetry_space

logger = logging.getLogger(__name__)

# A health probe pass stamps its rows with its start time and commits a few seconds
# later; an hour is only rolled up once this grace period after its end has passed.
ROLLUP_GRACE = timedelta(minutes=2)
# Commit after this many processed hours/days so a long backlog does not hold one huge transaction
COMMIT_EVERY = 24


def floor_to(ts: datetime, seconds: int) -> datetime:
    """Start of the UTC bucket of ``seconds`` length that contains the naive-UTC ``ts``."""
    epoch = int(ts.replace(tzinfo=UTC).timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC).replace(tzinfo=None)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _next_start(db: AsyncSession, rollup, resolution: int, source_ts) -> datetime | None:
    """First bucket that still needs a rollup: after the newest rollup, else the oldest source row."""
    newest = (await db.execute(
        select(func.max(rollup.bucket_start)).where(rollup.resolution == resolution)
    )).scalar()
    if newest is not None:
        return newest + timedelta(seconds=resolution)
    oldest = (await db.execute(select(func.min(source_ts)))).scalar()
    return floor_to(oldest, resolution) if oldest is not None else None


async def _skip_to_data(db: AsyncSession, ts_column, after: datetime, resolution: int, extra=()) -> datetime | None:
    """Bucket of the next source row at or after ``after`` (jumps over gaps without data)."""
    nxt = (await db.execute(select(func.min(ts_column)).where(ts_column >= after, *extra))).scalar()
    return floor_to(nxt, resolution) if nxt is not None else None


# ---------------------------------------------------------------------------
# Raw -> hourly
# ---------------------------------------------------------------------------

async def _health_hour_rows(db: AsyncSession, start: datetime, end: datetime) -> list[DeviceHealthRollup]:
    """Aggregate the health probes of [start, end) per device (SQL GROUP BY)."""
    s = DeviceHealthSample
    in_range = (s.timestamp >= start, s.timestamp < end)
    agg = await db.execute(
        select(
            s.device_id,
            func.count(),
            func.sum(case((s.is_online, 1), else_=0)),
            func.count(s.latency_ms),
            func.min(s.latency_ms),
            func.avg(s.latency_ms),
            func.max(s.latency_ms),
            func.avg(s.ports_up),
            func.max(s.ports_total),
        )
        .where(*in_range)
        .group_by(s.device_id)
    )
    rows = agg.all()
    if not rows:
        return []

    # Jitter: mean absolute difference of consecutive latencies, kept as sum + count
    prev = func.lag(s.latency_ms).over(partition_by=s.device_id, order_by=(s.timestamp, s.id))
    diffs = (
        select(s.device_id.label("device_id"), (s.latency_ms - prev).label("diff"))
        .where(*in_range, s.latency_ms.isnot(None))
        .subquery()
    )
    jitter = {
        r[0]: (float(r[1] or 0.0), int(r[2] or 0))
        for r in (await db.execute(
            select(diffs.c.device_id, func.sum(func.abs(diffs.c.diff)), func.count(diffs.c.diff))
            .group_by(diffs.c.device_id)
        )).all()
    }

    result = []
    for device_id, samples, online, lat_count, lat_min, lat_avg, lat_max, ports_up_avg, ports_total in rows:
        jitter_sum, jitter_count = jitter.get(device_id, (0.0, 0))
        result.append(DeviceHealthRollup(
            device_id=device_id,
            resolution=HOUR,
            bucket_start=start,
            samples=int(samples or 0),
            online=int(online or 0),
            latency_count=int(lat_count or 0),
            latency_min=lat_min,
            latency_avg=float(lat_avg) if lat_avg is not None else None,
            latency_max=lat_max,
            jitter_sum=jitter_sum,
            jitter_count=jitter_count,
            ports_up_avg=float(ports_up_avg or 0.0),
            ports_total=int(ports_total or 0),
        ))
    return result


def _net_totals(net_json: str | None) -> tuple[float, float] | None:
    """(rx, tx) bytes/s summed over all interfaces of one agent report."""
    if not net_json:
        return None
    try:
        data = json.loads(net_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    rx = tx = 0.0
    for iface in data.values():
        if isinstance(iface, dict):
            rx += float(iface.get("rx_bytes_sec") or 0)
            tx += float(iface.get("tx_bytes_sec") or 0)
    return rx, tx


def _disk_max_percent(disk_json: str | None) -> float | None:
    """Fill level of the fullest mount of one agent report."""
    if not disk_json:
        return None
    try:
        data = json.loads(disk_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    values = [float(d["percent"]) for d in data if isinstance(d, dict) and d.get("percent") is not None]
    return max(values) if values else None


def _max_or_none(values):
    values = [v for v in values if v is not None]
    return max(values) if values else None


def _metrics_rollup_from_rows(device_id: int, start: datetime, rows: list) -> DeviceMetricsRollup:
    """One hourly rollup from a device's raw agent reports (ordered by time)."""
    n = len(rows)
    temps = [r.temperature for r in rows if r.temperature is not None]
    nets = [t for t in (_net_totals(r.net_json) for r in rows) if t is not None]
    return DeviceMetricsRollup(
        device_id=device_id,
        resolution=HOUR,
        bucket_start=start,
        samples=n,
        cpu_avg=sum(r.cpu_percent or 0.0 for r in rows) / n,
        cpu_max=max(r.cpu_percent or 0.0 for r in rows),
        ram_percent_avg=sum(r.ram_percent or 0.0 for r in rows) / n,
        ram_percent_max=max(r.ram_percent or 0.0 for r in rows),
        ram_used_mb_avg=sum(r.ram_used_mb or 0 for r in rows) / n,
        ram_total_mb=max(r.ram_total_mb or 0 for r in rows),
        temp_count=len(temps),
        temp_avg=sum(temps) / len(temps) if temps else None,
        temp_max=max(temps) if temps else None,
        disk_percent_max=_max_or_none(_disk_max_percent(r.disk_json) for r in rows),
        net_rx_avg=sum(t[0] for t in nets) / len(nets) if nets else 0.0,
        net_rx_max=max((t[0] for t in nets), default=0.0),
        net_tx_avg=sum(t[1] for t in nets) / len(nets) if nets else 0.0,
        net_tx_max=max((t[1] for t in nets), default=0.0),
        disk_json=next((r.disk_json for r in reversed(rows) if r.disk_json), None),
        net_json=next((r.net_json for r in reversed(rows) if r.net_json), None),
    )


async def _metrics_hour_rows(db: AsyncSession, start: datetime, end: datetime) -> list[DeviceMetricsRollup]:
    """Aggregate the agent reports of [start, end) per device (in Python: disk/net are JSON)."""
    m = DeviceMetrics
    res = await db.execute(
        select(m.device_id, m.cpu_percent, m.ram_percent, m.ram_used_mb, m.ram_total_mb,
               m.temperature, m.disk_json, m.net_json)
        .where(m.timestamp >= start, m.timestamp < end)
        .order_by(m.device_id, m.timestamp, m.id)
    )
    by_device: dict[int, list] = defaultdict(list)
    for row in res.all():
        by_device[row.device_id].append(row)
    return [_metrics_rollup_from_rows(dev_id, start, rows) for dev_id, rows in by_device.items()]


async def _rollup_hours(db: AsyncSession, now: datetime, rollup, ts_column, build) -> int:
    """Create hourly rollups for every complete hour not rolled up yet; returns rows added."""
    end = floor_to(now - ROLLUP_GRACE, HOUR)
    hour = await _next_start(db, rollup, HOUR, ts_column)
    added = processed = 0
    while hour is not None and hour < end:
        nxt = hour + timedelta(hours=1)
        rows = await build(db, hour, nxt)
        if rows:
            db.add_all(rows)
            added += len(rows)
            processed += 1
            if processed % COMMIT_EVERY == 0:
                await db.commit()
            hour = nxt
        else:
            hour = await _skip_to_data(db, ts_column, nxt, HOUR)
    await db.commit()
    return added


async def rollup_health_hours(db: AsyncSession, now: datetime | None = None) -> int:
    return await _rollup_hours(db, now or _utcnow_naive(), DeviceHealthRollup,
                               DeviceHealthSample.timestamp, _health_hour_rows)


async def rollup_metrics_hours(db: AsyncSession, now: datetime | None = None) -> int:
    return await _rollup_hours(db, now or _utcnow_naive(), DeviceMetricsRollup,
                               DeviceMetrics.timestamp, _metrics_hour_rows)


# ---------------------------------------------------------------------------
# Hourly -> daily
# ---------------------------------------------------------------------------

def _weighted(pairs) -> float | None:
    """Weighted mean of (value, weight) pairs, ignoring missing values."""
    total = weight = 0.0
    for value, w in pairs:
        if value is not None and w:
            total += value * w
            weight += w
    return total / weight if weight else None


def combine_health(device_id: int, resolution: int, start: datetime, parts: list) -> DeviceHealthRollup:
    """Merge health rollups of smaller buckets into one bucket of ``resolution``."""
    return DeviceHealthRollup(
        device_id=device_id,
        resolution=resolution,
        bucket_start=start,
        samples=sum(p.samples for p in parts),
        online=sum(p.online for p in parts),
        latency_count=sum(p.latency_count for p in parts),
        latency_min=min((p.latency_min for p in parts if p.latency_min is not None), default=None),
        latency_avg=_weighted((p.latency_avg, p.latency_count) for p in parts),
        latency_max=_max_or_none(p.latency_max for p in parts),
        jitter_sum=sum(p.jitter_sum for p in parts),
        jitter_count=sum(p.jitter_count for p in parts),
        ports_up_avg=_weighted((p.ports_up_avg, p.samples) for p in parts) or 0.0,
        ports_total=max((p.ports_total for p in parts), default=0),
    )


def combine_metrics(device_id: int, resolution: int, start: datetime, parts: list) -> DeviceMetricsRollup:
    """Merge metrics rollups of smaller buckets (ordered by time) into one bucket."""
    def avg(attr: str) -> float:
        return _weighted((getattr(p, attr), p.samples) for p in parts) or 0.0

    temp_count = sum(p.temp_count for p in parts)
    return DeviceMetricsRollup(
        device_id=device_id,
        resolution=resolution,
        bucket_start=start,
        samples=sum(p.samples for p in parts),
        cpu_avg=avg("cpu_avg"),
        cpu_max=max(p.cpu_max for p in parts),
        ram_percent_avg=avg("ram_percent_avg"),
        ram_percent_max=max(p.ram_percent_max for p in parts),
        ram_used_mb_avg=avg("ram_used_mb_avg"),
        ram_total_mb=max(p.ram_total_mb for p in parts),
        temp_count=temp_count,
        temp_avg=_weighted((p.temp_avg, p.temp_count) for p in parts) if temp_count else None,
        temp_max=_max_or_none(p.temp_max for p in parts),
        disk_percent_max=_max_or_none(p.disk_percent_max for p in parts),
        net_rx_avg=avg("net_rx_avg"),
        net_rx_max=max(p.net_rx_max for p in parts),
        net_tx_avg=avg("net_tx_avg"),
        net_tx_max=max(p.net_tx_max for p in parts),
        disk_json=next((p.disk_json for p in reversed(parts) if p.disk_json), None),
        net_json=next((p.net_json for p in reversed(parts) if p.net_json), None),
    )


async def _next_start_daily(db: AsyncSession, rollup) -> datetime | None:
    newest = (await db.execute(select(func.max(rollup.bucket_start)).where(rollup.resolution == DAY))).scalar()
    if newest is not None:
        return newest + timedelta(days=1)
    oldest = (await db.execute(select(func.min(rollup.bucket_start)).where(rollup.resolution == HOUR))).scalar()
    return floor_to(oldest, DAY) if oldest is not None else None


async def _rollup_days(db: AsyncSession, now: datetime, rollup, combine) -> int:
    """Create daily rollups from the hourly ones for every complete day not rolled up yet."""
    # A day is complete once its last hour can be rolled up
    end = floor_to(floor_to(now - ROLLUP_GRACE, HOUR), DAY)
    is_hourly = rollup.resolution == HOUR
    day = await _next_start_daily(db, rollup)
    added = processed = 0
    while day is not None and day < end:
        nxt = day + timedelta(days=1)
        res = await db.execute(
            select(rollup)
            .where(is_hourly, rollup.bucket_start >= day, rollup.bucket_start < nxt)
            .order_by(rollup.device_id, rollup.bucket_start)
        )
        by_device: dict[int, list] = defaultdict(list)
        for part in res.scalars().all():
            by_device[part.device_id].append(part)
        if by_device:
            db.add_all([combine(dev_id, DAY, day, parts) for dev_id, parts in by_device.items()])
            added += len(by_device)
            processed += 1
            if processed % COMMIT_EVERY == 0:
                await db.commit()
            day = nxt
        else:
            day = await _skip_to_data(db, rollup.bucket_start, nxt, DAY, extra=(is_hourly,))
    await db.commit()
    return added


async def rollup_health_days(db: AsyncSession, now: datetime | None = None) -> int:
    return await _rollup_days(db, now or _utcnow_naive(), DeviceHealthRollup, combine_health)


async def rollup_metrics_days(db: AsyncSession, now: datetime | None = None) -> int:
    return await _rollup_days(db, now or _utcnow_naive(), DeviceMetricsRollup, combine_metrics)


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------

async def _covered_until(db: AsyncSession, rollup, resolution: int) -> datetime | None:
    """End of the newest rollup of ``resolution``: older source rows are safe to drop."""
    newest = (await db.execute(
        select(func.max(rollup.bucket_start)).where(rollup.resolution == resolution)
    )).scalar()
    return newest + timedelta(seconds=resolution) if newest is not None else None


async def prune_telemetry(db: AsyncSession, now: datetime, retention: TelemetryRetention) -> dict[str, int]:
    """Delete rows beyond each tier's retention; returns deleted rows per tier."""
    raw_cutoff = floor_to(now - timedelta(hours=retention.raw_hours), HOUR)
    hourly_cutoff = floor_to(now - timedelta(days=retention.hourly_days), DAY)
    daily_cutoff = floor_to(now - timedelta(days=retention.daily_days), DAY)

    deleted: dict[str, int] = {}
    for name, raw_model, ts_column, rollup in (
        ("health", DeviceHealthSample, DeviceHealthSample.timestamp, DeviceHealthRollup),
        ("metrics", DeviceMetrics, DeviceMetrics.timestamp, DeviceMetricsRollup),
    ):
        # Raw rows go only once their hour is rolled up, hourly rows once their day is
        hour_done = await _covered_until(db, rollup, HOUR)
        day_done = await _covered_until(db, rollup, DAY)

        raw_deleted = 0
        if hour_done is not None:
            raw_deleted = (await db.execute(
                delete(raw_model).where(ts_column < min(raw_cutoff, hour_done))
            )).rowcount or 0
        hourly_deleted = 0
        if day_done is not None:
            hourly_deleted = (await db.execute(
                delete(rollup).where(rollup.resolution == HOUR, rollup.bucket_start < min(hourly_cutoff, day_done))
            )).rowcount or 0
        daily_deleted = (await db.execute(
            delete(rollup).where(rollup.resolution == DAY, rollup.bucket_start < daily_cutoff)
        )).rowcount or 0

        deleted[f"{name}_raw"] = raw_deleted
        deleted[f"{name}_hourly"] = hourly_deleted
        deleted[f"{name}_daily"] = daily_deleted
    await db.commit()
    return deleted


async def run_telemetry_maintenance(db: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Roll up, prune and reclaim space; returns counters for the log."""
    now = now or _utcnow_naive()
    retention = await get_retention(db)
    stats = {
        "health_hourly_added": await rollup_health_hours(db, now),
        "metrics_hourly_added": await rollup_metrics_hours(db, now),
        "health_daily_added": await rollup_health_days(db, now),
        "metrics_daily_added": await rollup_metrics_days(db, now),
    }
    deleted = await prune_telemetry(db, now, retention)
    stats.update({f"{k}_deleted": v for k, v in deleted.items()})
    if any(deleted.values()):
        await reclaim_telemetry_space(db)
    return stats
