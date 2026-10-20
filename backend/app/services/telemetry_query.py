"""Read health and metrics history from the right tier for a time window.

A window is served from one preferred tier (raw for short windows, hourly or daily
rollups for long ones) and stitched with the others where that tier has no data:

* newer than the preferred tier's last bucket (the hour that is not rolled up
  yet) comes from the finer tiers, ultimately from the raw rows,
* older than the preferred tier's first bucket (its retention is shorter than the
  window) comes from the coarser tiers.

Boundaries fall on bucket edges, so no measurement is counted twice. Every source
is returned as the same point type (a raw row is a bucket with one sample), so the
callers compute uptime, latency and chart series without caring where a point
came from.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import DeviceMetrics
from app.models.device import DeviceHealthSample
from app.models.telemetry import DAY, HOUR, DeviceHealthRollup, DeviceMetricsRollup
from app.services.telemetry_rollups import floor_to
from app.services.telemetry_store import TelemetryRetention, get_retention

RAW = 0
# Coarse to fine
TIERS = (DAY, HOUR, RAW)


def choose_resolution(window: timedelta, retention: TelemetryRetention) -> int:
    """Preferred tier for a window: raw up to 48 h (or the raw retention), hourly up to its retention."""
    if window <= timedelta(hours=min(retention.raw_hours, 48)):
        return RAW
    if window <= timedelta(days=retention.hourly_days):
        return HOUR
    return DAY


def _ceil_to(ts: datetime, seconds: int) -> datetime:
    floored = floor_to(ts, seconds)
    return floored if floored == ts else floored + timedelta(seconds=seconds)


@dataclass
class Segment:
    tier: int
    start: datetime          # inclusive
    end: datetime | None     # exclusive; None = open (raw up to now)


def plan_segments(
    window_start: datetime,
    preferred: int,
    coverage: dict[int, tuple[datetime, datetime] | None],
) -> list[Segment]:
    """Split [window_start, now) into per-tier segments, oldest first.

    ``coverage`` maps each tier to the (first bucket start, last bucket end) it
    holds, or None when it is empty; raw rows always reach up to now.
    """
    segments: list[Segment] = []
    cursor = window_start
    for tier in TIERS[TIERS.index(preferred):]:
        if tier == RAW:
            segments.append(Segment(RAW, cursor, None))
            break
        cov = coverage.get(tier)
        if not cov or cov[1] <= cursor:
            continue
        segments.append(Segment(tier, cursor, cov[1]))
        cursor = cov[1]

    # The oldest segment's tier may only start inside the window: fill with coarser tiers
    first = segments[0]
    cov = coverage.get(first.tier)
    earliest = max(first.start, cov[0]) if cov else datetime.max
    for tier in reversed(TIERS[:TIERS.index(first.tier)]):
        if earliest <= window_start:
            break
        coarse = coverage.get(tier)
        # Nothing older than the bucket the finer tier starts in: the recording simply began
        # there, and a coarse bucket would only shift the first, partial bucket in time
        if not coarse or coarse[0] >= floor_to(min(earliest, coarse[1]), tier):
            continue
        boundary = _ceil_to(min(earliest, coarse[1]), tier)
        segments[0].start = max(segments[0].start, boundary)
        segments.insert(0, Segment(tier, window_start, boundary))
        earliest = max(window_start, coarse[0])
    return segments


async def _coverage(db: AsyncSession, raw_ts, rollup) -> dict[int, tuple[datetime, datetime] | None]:
    """(first bucket start, last bucket end) per tier; raw reaches up to now."""
    coverage: dict[int, tuple[datetime, datetime] | None] = {}
    oldest_raw = (await db.execute(select(func.min(raw_ts)))).scalar()
    coverage[RAW] = (oldest_raw, datetime.max) if oldest_raw is not None else None
    res = await db.execute(
        select(rollup.resolution, func.min(rollup.bucket_start), func.max(rollup.bucket_start))
        .group_by(rollup.resolution)
    )
    found = {r[0]: (r[1], r[2] + timedelta(seconds=r[0])) for r in res.all()}
    coverage[HOUR] = found.get(HOUR)
    coverage[DAY] = found.get(DAY)
    return coverage


def _range_filter(column, segment: Segment) -> list:
    conditions = [column >= segment.start]
    if segment.end is not None:
        conditions.append(column < segment.end)
    return conditions


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class HealthPoint:
    """Probes of one device in one bucket (a raw probe is a bucket of one)."""

    timestamp: datetime
    samples: int
    online: int
    latency_count: int
    latency_min: float | None
    latency_avg: float | None
    latency_max: float | None
    jitter_sum: float = 0.0
    jitter_count: int = 0
    ports_up: float = 0.0
    ports_total: int = 0
    probe_type: str | None = None
    is_raw: bool = True

    @property
    def is_online(self) -> bool:
        return self.online > 0

    @property
    def latency_ms(self) -> float | None:
        return self.latency_avg

    @property
    def uptime_pct(self) -> float:
        return round(self.online / self.samples * 100.0, 1) if self.samples else 0.0


def health_point_from_sample(s) -> HealthPoint:
    """HealthPoint of one raw probe (a DeviceHealthSample or a row with its columns)."""
    latency = s.latency_ms
    return HealthPoint(
        timestamp=s.timestamp,
        samples=1,
        online=1 if s.is_online else 0,
        latency_count=1 if latency is not None else 0,
        latency_min=latency,
        latency_avg=latency,
        latency_max=latency,
        ports_up=float(getattr(s, "ports_up", 0) or 0),
        ports_total=int(getattr(s, "ports_total", 0) or 0),
        probe_type=getattr(s, "probe_type", None),
    )


def health_point_from_rollup(r) -> HealthPoint:
    return HealthPoint(
        timestamp=r.bucket_start,
        samples=r.samples,
        online=r.online,
        latency_count=r.latency_count,
        latency_min=r.latency_min,
        latency_avg=r.latency_avg,
        latency_max=r.latency_max,
        jitter_sum=r.jitter_sum,
        jitter_count=r.jitter_count,
        ports_up=r.ports_up_avg,
        ports_total=r.ports_total,
        is_raw=False,
    )


async def load_health_points(
    db: AsyncSession,
    device_ids: list[int],
    window_start: datetime,
    now: datetime,
    retention: TelemetryRetention | None = None,
) -> dict[int, list[HealthPoint]]:
    """Health points per device for [window_start, now), oldest first (naive UTC)."""
    if not device_ids:
        return {}
    retention = retention or await get_retention(db)
    preferred = choose_resolution(now - window_start, retention)
    coverage = await _coverage(db, DeviceHealthSample.timestamp, DeviceHealthRollup)
    points: dict[int, list[HealthPoint]] = defaultdict(list)

    for segment in plan_segments(window_start, preferred, coverage):
        if segment.tier == RAW:
            s = DeviceHealthSample
            res = await db.execute(
                select(s.device_id, s.timestamp, s.is_online, s.latency_ms, s.probe_type, s.ports_up, s.ports_total)
                .where(s.device_id.in_(device_ids), *_range_filter(s.timestamp, segment))
                .order_by(s.device_id, s.timestamp)
            )
            for row in res.all():
                points[row.device_id].append(health_point_from_sample(row))
        else:
            r = DeviceHealthRollup
            res = await db.execute(
                select(r)
                .where(r.device_id.in_(device_ids), r.resolution == segment.tier,
                       *_range_filter(r.bucket_start, segment))
                .order_by(r.device_id, r.bucket_start)
            )
            for rollup in res.scalars().all():
                points[rollup.device_id].append(health_point_from_rollup(rollup))

    for dev_points in points.values():
        dev_points.sort(key=lambda p: p.timestamp)
    return points


# ---------------------------------------------------------------------------
# Agent metrics
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MetricPoint:
    """Agent reports of one device in one bucket (a raw report is a bucket of one)."""

    timestamp: datetime
    samples: int
    cpu_avg: float
    cpu_max: float
    ram_percent_avg: float
    ram_percent_max: float
    ram_used_mb_avg: float
    ram_total_mb: int
    temp_count: int
    temp_avg: float | None
    temp_max: float | None
    disk_json: str | None
    net_json: str | None
    is_raw: bool = True


def metric_point_from_row(m) -> MetricPoint:
    return MetricPoint(
        timestamp=m.timestamp,
        samples=1,
        cpu_avg=m.cpu_percent or 0.0,
        cpu_max=m.cpu_percent or 0.0,
        ram_percent_avg=m.ram_percent or 0.0,
        ram_percent_max=m.ram_percent or 0.0,
        ram_used_mb_avg=float(m.ram_used_mb or 0),
        ram_total_mb=m.ram_total_mb or 0,
        temp_count=1 if m.temperature is not None else 0,
        temp_avg=m.temperature,
        temp_max=m.temperature,
        disk_json=m.disk_json,
        net_json=m.net_json,
    )


def metric_point_from_rollup(r) -> MetricPoint:
    return MetricPoint(
        timestamp=r.bucket_start,
        samples=r.samples,
        cpu_avg=r.cpu_avg,
        cpu_max=r.cpu_max,
        ram_percent_avg=r.ram_percent_avg,
        ram_percent_max=r.ram_percent_max,
        ram_used_mb_avg=r.ram_used_mb_avg,
        ram_total_mb=r.ram_total_mb,
        temp_count=r.temp_count,
        temp_avg=r.temp_avg,
        temp_max=r.temp_max,
        disk_json=r.disk_json,
        net_json=r.net_json,
        is_raw=False,
    )


async def load_metric_points(
    db: AsyncSession,
    device_id: int,
    window_start: datetime,
    now: datetime,
    retention: TelemetryRetention | None = None,
) -> list[MetricPoint]:
    """Agent metric points of one device for [window_start, now), oldest first (naive UTC)."""
    retention = retention or await get_retention(db)
    preferred = choose_resolution(now - window_start, retention)
    coverage = await _coverage(db, DeviceMetrics.timestamp, DeviceMetricsRollup)
    points: list[MetricPoint] = []

    for segment in plan_segments(window_start, preferred, coverage):
        if segment.tier == RAW:
            m = DeviceMetrics
            res = await db.execute(
                select(m).where(m.device_id == device_id, *_range_filter(m.timestamp, segment))
                .order_by(m.timestamp)
            )
            points.extend(metric_point_from_row(row) for row in res.scalars().all())
        else:
            r = DeviceMetricsRollup
            res = await db.execute(
                select(r).where(r.device_id == device_id, r.resolution == segment.tier,
                                *_range_filter(r.bucket_start, segment))
                .order_by(r.bucket_start)
            )
            points.extend(metric_point_from_rollup(row) for row in res.scalars().all())

    points.sort(key=lambda p: p.timestamp)
    return points
