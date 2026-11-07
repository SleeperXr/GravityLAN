"""Health summary and historical telemetry API endpoints for GravityLAN."""

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import get_current_admin
from app.api.summary import get_summary
from app.database import get_db
from app.models.agent import AgentToken, DeviceMetrics
from app.models.device import Device, DeviceHistory
from app.scanner.utils import ensure_utc
from app.services.agent_activity import active_window, load_intervals
from app.schemas.health import (
    AgentHealthAlerts,
    DeviceHealthDetailResponse,
    DeviceHealthItem,
    HealthIncident,
    HealthOverviewKPIs,
    HealthOverviewResponse,
    HealthSamplePoint,
    HealthSummaryResponse,
    LatencyStats,
    ServiceHealthItem,
    UptimeStats,
)
from app.services.telemetry_query import HealthPoint, health_point_from_sample, load_health_points
from app.version import VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/summary", response_model=HealthSummaryResponse)
async def get_health_summary(
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
) -> HealthSummaryResponse:
    """Fetch a single aggregated status summary representing the network's health."""
    now = datetime.now(UTC)

    # 1. Device counts
    devices_res = await db.execute(
        select(Device.id, Device.is_online).where(
            Device.is_hidden == False,
            Device.ip_placeholder == False,
        )
    )
    devices = devices_res.all()
    total_devices = len(devices)
    online_devices = sum(1 for d in devices if d.is_online)
    offline_devices = total_devices - online_devices

    # 2. Agent counts
    agents_res = await db.execute(select(AgentToken))
    agents = agents_res.scalars().all()
    total_agents = len(agents)

    offline_agents = 0
    active_device_ids = set()
    intervals = await load_intervals(db)
    for agent in agents:
        last_seen = ensure_utc(agent.last_seen)
        is_active = bool(agent.is_active and last_seen and (now - last_seen).total_seconds() < active_window(intervals.get(agent.device_id)))
        if not is_active:
            offline_agents += 1
        else:
            active_device_ids.add(agent.device_id)

    # Calculate high CPU (> 90%) and high temperature (> 75°C) active agents
    high_cpu = 0
    high_temp = 0
    if active_device_ids:
        metrics_res = await db.execute(
            select(DeviceMetrics).where(DeviceMetrics.id.in_(
                select(func.max(DeviceMetrics.id)).where(DeviceMetrics.device_id.in_(active_device_ids)).group_by(DeviceMetrics.device_id)
            ))
        )
        latest_metrics = metrics_res.scalars().all()
        for m in latest_metrics:
            if m.device_id in active_device_ids:
                if m.cpu_percent > 90.0:
                    high_cpu += 1
                if m.temperature is not None and m.temperature > 75.0:
                    high_temp += 1

    # 3. Active issues by type
    summary = await get_summary(token, db)
    active_issues_count = len(summary.active_issues)
    issues_by_type = {"agent_offline": 0, "service_down": 0}
    for issue in summary.active_issues:
        issues_by_type[issue.type] = issues_by_type.get(issue.type, 0) + 1

    # 4. Notifications
    unread_res = await db.execute(select(func.count(DeviceHistory.id)))
    unread_count = unread_res.scalar_one()

    cutoff_30min = now.replace(tzinfo=None) - timedelta(minutes=30)
    fresh_res = await db.execute(select(func.count(DeviceHistory.id)).where(DeviceHistory.timestamp >= cutoff_30min))
    fresh_count = fresh_res.scalar_one()

    # 5. Scanner
    scanner_status = summary.scanner.status
    is_scanner_running = scanner_status in ("running", "discovering", "identifying")
    last_scan = summary.scanner.last_scan
    stale_hours = None
    if last_scan:
        stale_hours = round((now - last_scan).total_seconds() / 3600.0, 1)

    return HealthSummaryResponse(
        api_version=VERSION,
        devices={
            "total": total_devices,
            "online": online_devices,
            "offline": offline_devices
        },
        agents={
            "total": total_agents,
            "high_cpu": high_cpu,
            "high_temp": high_temp,
            "offline_agents": offline_agents
        },
        issues={
            "active": active_issues_count,
            "by_type": issues_by_type
        },
        notifications={
            "unread": unread_count,
            "fresh_30min": fresh_count
        },
        scanner={
            "running": is_scanner_running,
            "last_run": last_scan,
            "stale_hours": stale_hours
        }
    )


# ---------------------------------------------------------------------------
# Historical Health Overview & Telemetry
# ---------------------------------------------------------------------------

def _parse_period_window(period: str, now: datetime) -> tuple[datetime, int]:
    """Parse duration and bucket count for period (24h, 7d, 30d)."""
    if period == "7d":
        return now - timedelta(days=7), 28  # 6-hour buckets
    if period == "30d":
        return now - timedelta(days=30), 30  # 1-day buckets
    return now - timedelta(hours=24), 24  # 1-hour buckets


def _as_points(samples: list) -> list[HealthPoint]:
    """Accept HealthPoints or raw DeviceHealthSample-like rows."""
    return [s if isinstance(s, HealthPoint) else health_point_from_sample(s) for s in samples]


def _latency_stats(points: list[HealthPoint]) -> LatencyStats:
    """Latency min/avg/max/jitter over raw probes and rollup buckets alike."""
    current_ms = None
    probe_type = None
    min_ms = avg_ms = max_ms = jitter_ms = None

    measured = [p for p in points if p.latency_count]
    if measured:
        min_ms = round(min(p.latency_min for p in measured if p.latency_min is not None), 1)
        max_ms = round(max(p.latency_max for p in measured if p.latency_max is not None), 1)
        total = sum(p.latency_count for p in measured)
        avg_ms = round(sum(p.latency_avg * p.latency_count for p in measured) / total, 1)

        # Rollups carry their own jitter sums; raw probes add consecutive differences
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

    # Sparkline: downsample up to 20 representative values across the window
    sparkline: list[float | None] = []
    if points:
        step = max(1, len(points) // 20)
        for i in range(0, len(points), step):
            sparkline.append(points[i].latency_ms)
        if len(sparkline) > 20:
            sparkline = sparkline[-20:]

    return LatencyStats(
        current_ms=current_ms,
        min_ms=min_ms,
        avg_ms=avg_ms,
        max_ms=max_ms,
        jitter_ms=jitter_ms,
        sparkline=sparkline,
        probe_type=probe_type,
    )


def _uptime_pct(online: int, samples: int) -> float:
    return round(online / samples * 100.0, 1)


def _compute_uptime_and_latency(
    dev: Device,
    samples: list,
    now: datetime,
    window_start: datetime,
    bucket_count: int
) -> tuple[UptimeStats, LatencyStats]:
    """Calculate availability SLA and latency metrics from time-series points.

    ``samples`` are HealthPoints (raw probes and hourly/daily rollups, see
    app.services.telemetry_query) or raw DeviceHealthSample rows; every value is
    weighted by the number of probes behind it.
    """
    points = _as_points(samples)
    latency_stats = _latency_stats(points)

    # Uptime & Heartbeat Bars
    total_seconds = (now - window_start).total_seconds()
    bucket_sec = total_seconds / bucket_count
    bars: list[float | None] = [None] * bucket_count
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
            bars[i] = _uptime_pct(bucket_online[i], bucket_samples[i])
        else:
            # If no probe happened in bucket yet, fallback based on current device status
            b_end = window_start + timedelta(seconds=(i + 1) * bucket_sec)
            dev_first_seen = ensure_utc(dev.first_seen) or now
            if dev_first_seen <= b_end:
                bars[i] = 100.0 if dev.is_online else 0.0

    # Overall uptime percentage in window
    total_samples = sum(p.samples for p in points)
    if total_samples:
        uptime_pct = _uptime_pct(sum(p.online for p in points), total_samples)
    else:
        uptime_pct = 100.0 if dev.is_online else 0.0

    uptime_24h = _uptime_pct(online_24h, total_24h) if total_24h else uptime_pct
    uptime_7d = _uptime_pct(online_7d, total_7d) if total_7d else uptime_pct

    uptime_stats = UptimeStats(
        uptime_pct=uptime_pct,
        uptime_24h=uptime_24h,
        uptime_7d=uptime_7d,
        uptime_30d=uptime_pct,
        history_bars=bars,
    )

    return uptime_stats, latency_stats


def _certificate_penalty(svc: ServiceHealthItem) -> int:
    """Points lost for a certificate that runs out soon (none when the service ignores SSL)."""
    days = svc.ssl_expiry_days
    if getattr(svc, "ignore_ssl", False) or days is None:
        return 0
    if days <= 3:
        return 15
    if days <= 14:
        return 5
    return 0


def _maintenance_penalty(agent: AgentHealthAlerts) -> int:
    """Points lost for pending security patches and a needed reboot."""
    return (10 if agent.patch_security > 0 else 0) + (5 if agent.reboot_required else 0)


def _score_part_time_device(
    dev: Device, latency: LatencyStats, services: list[ServiceHealthItem], agent: AgentHealthAlerts | None
) -> tuple[int, str]:
    """A device without offline alert (TV, PC, laptop, phone) may sleep; when on, only certificates and patches count."""
    is_sleeping = (
        not dev.is_online
        or (dev.missed_scans or 0) > 0
        or latency.current_ms is None
        or bool(services and all(not s.is_up for s in services))
    )
    if is_sleeping:
        return 100, "standby"

    score = 100 - sum(_certificate_penalty(svc) for svc in services)
    if agent and agent.is_active:
        score -= _maintenance_penalty(agent)
    return score, "healthy" if score >= 85 else "degraded"


def _reachability_penalty(dev: Device, uptime: UptimeStats, latency: LatencyStats) -> int:
    """Points lost for missed scans, uptime below 99 % and high latency."""
    penalty = 0
    if dev.missed_scans > 0:
        penalty += min(30, dev.missed_scans * 15)
    if uptime.uptime_pct < 99.0:
        penalty += int((99.0 - uptime.uptime_pct) * 0.8)
    if latency.avg_ms is not None:
        if latency.avg_ms > 150:
            penalty += 15
        elif latency.avg_ms > 60:
            penalty += 8
    return penalty


def _service_penalty(services: list[ServiceHealthItem]) -> int:
    """20 points per service that is down; a running one can lose points for its certificate."""
    return sum(20 if not svc.is_up else _certificate_penalty(svc) for svc in services)


def _agent_host_gone(agent: AgentHealthAlerts | None, latency: LatencyStats, services: list[ServiceHealthItem]) -> bool:
    """The agent stopped reporting and nothing else answers: the host counts as offline."""
    return bool(
        agent and agent.has_agent and not agent.is_active
        and latency.current_ms is None
        and (not services or all(not s.is_up for s in services))
    )


def _agent_penalty(agent: AgentHealthAlerts | None) -> int:
    """Points lost for a silent agent, or for patches, reboot, CPU and temperature of an active one."""
    if not (agent and agent.has_agent):
        return 0
    if not agent.is_active:
        return 35
    penalty = _maintenance_penalty(agent)
    if agent.cpu_percent is not None and agent.cpu_percent > 90:
        penalty += 10
    if agent.temperature is not None and agent.temperature > 75:
        penalty += 10
    return penalty


def _monitored_status(
    dev: Device, score: int, latency: LatencyStats, services: list[ServiceHealthItem], agent: AgentHealthAlerts | None
) -> str:
    if dev.missed_scans > 0:
        return "flapping"
    if score < 60 or any(not s.is_up for s in services) or (agent and agent.has_agent and not agent.is_active):
        return "critical"
    if score < 85 or (latency.avg_ms and latency.avg_ms > 60):
        return "degraded"
    return "healthy"


def _calculate_health_score(
    dev: Device,
    uptime: UptimeStats,
    latency: LatencyStats,
    services: list[ServiceHealthItem],
    agent: AgentHealthAlerts | None
) -> tuple[int, str]:
    """Score 0-100 and status of a device; 24/7 infrastructure is rated stricter than devices that may sleep."""
    if not getattr(dev, "alert_offline", True):
        return _score_part_time_device(dev, latency, services, agent)

    # 24/7 monitored infrastructure (servers, gateways, switches, APs)
    if not dev.is_online:
        return 0, "offline"

    reachability = _reachability_penalty(dev, uptime, latency)
    if _agent_host_gone(agent, latency, services):
        return 0, "offline"

    score = 100 - reachability - _service_penalty(services) - _agent_penalty(agent)
    score = max(0, min(100, score))
    return score, _monitored_status(dev, score, latency, services, agent)


_OVERVIEW_CRITICAL = ("offline", "service_down", "down")
_DETAIL_CRITICAL = ("offline", "service_down")
MAX_OVERVIEW_INCIDENTS = 40
MAX_DETAIL_POINTS = 120
# What an agent block shows before the agent's first report
_NO_METRICS = SimpleNamespace(
    cpu_percent=None, ram_percent=None, temperature=None, patch_available=0, patch_security=0,
    reboot_required=False, major_upgrade_available=None,
)


def _display_name(dev: Device) -> str:
    return dev.display_name or dev.hostname or dev.ip


def _service_items(dev: Device) -> list[ServiceHealthItem]:
    return [
        ServiceHealthItem(
            id=s.id,
            name=s.name,
            protocol=s.protocol,
            port=s.port,
            is_up=s.is_up,
            latency_ms=s.latency_ms,
            ssl_expiry_days=s.ssl_expiry_days,
            ignore_ssl=bool(s.ignore_ssl),
        )
        for s in dev.services
    ]


def _agent_alerts(
    dev: Device, agent_token: AgentToken | None, metric: DeviceMetrics | None, now: datetime, interval: int | None
) -> AgentHealthAlerts | None:
    """The agent block of a device that has an agent or a token; None otherwise."""
    if not (dev.has_agent or agent_token):
        return None
    is_active = bool(
        agent_token
        and agent_token.last_seen
        and (now - ensure_utc(agent_token.last_seen)).total_seconds() < active_window(interval)
    )
    m = metric or _NO_METRICS
    return AgentHealthAlerts(
        has_agent=True,
        agent_version=agent_token.agent_version if agent_token else None,
        is_active=is_active,
        cpu_percent=m.cpu_percent,
        ram_percent=m.ram_percent,
        temperature=m.temperature,
        patch_available=m.patch_available,
        patch_security=m.patch_security,
        reboot_required=m.reboot_required,
        major_upgrade_available=m.major_upgrade_available,
    )


def _device_item(
    dev: Device,
    score: int,
    status: str,
    latency: LatencyStats,
    uptime: UptimeStats,
    services: list[ServiceHealthItem],
    agent: AgentHealthAlerts | None,
) -> DeviceHealthItem:
    return DeviceHealthItem(
        id=dev.id,
        ip=dev.ip,
        display_name=_display_name(dev),
        hostname=dev.hostname,
        device_type=dev.device_type,
        group_id=dev.group_id,
        group_name=dev.group.name if dev.group else None,
        is_online=dev.is_online,
        alert_offline=bool(dev.alert_offline),
        missed_scans=dev.missed_scans or 0,
        health_score=score,
        health_status=status,
        latency=latency,
        uptime=uptime,
        services=services,
        agent=agent,
        ip_changed_at=ensure_utc(dev.ip_changed_at),
        status_changed_at=ensure_utc(dev.status_changed_at),
        last_seen=ensure_utc(dev.last_seen),
    )


def _hidden_while_asleep(dev: Device, status: str) -> bool:
    """A device that may sleep (no offline alert) does not report going offline or flapping."""
    return not getattr(dev, "alert_offline", True) and status in ("offline", "flapping")


def _incident(hist: DeviceHistory, dev: Device, critical: tuple[str, ...], now: datetime) -> HealthIncident:
    severity = "critical" if hist.status in critical else "warn" if hist.status == "flapping" else "info"
    return HealthIncident(
        id=hist.id,
        device_id=dev.id,
        device_name=_display_name(dev),
        device_ip=dev.ip,
        status=hist.status,
        severity=severity,
        message=hist.message,
        timestamp=ensure_utc(hist.timestamp) or now,
    )


def _overview_incidents(rows, now: datetime) -> list[HealthIncident]:
    incidents: list[HealthIncident] = []
    for hist, dev in rows:
        if _hidden_while_asleep(dev, hist.status):
            continue
        incidents.append(_incident(hist, dev, _OVERVIEW_CRITICAL, now))
        if len(incidents) >= MAX_OVERVIEW_INCIDENTS:
            break
    return incidents


def _ssl_warning(svc: ServiceHealthItem) -> bool:
    return not svc.ignore_ssl and svc.ssl_expiry_days is not None and svc.ssl_expiry_days <= 14


def _rounded_mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _overview_kpis(items: list[DeviceHealthItem]) -> HealthOverviewKPIs:
    """Network-wide figures over the device entries of the overview."""
    scores = [d.health_score for d in items]
    alerting = [d for d in items if getattr(d, "alert_offline", True)]
    return HealthOverviewKPIs(
        network_health_score=round(sum(scores) / len(scores)) if scores else 100,
        total_devices=len(items),
        online_devices=sum(1 for d in items if d.is_online and d.health_status != "offline"),
        offline_devices=sum(1 for d in alerting if not d.is_online or d.health_status == "offline"),
        flapping_devices=sum(1 for d in items if d.health_status == "flapping"),
        avg_latency_ms=_rounded_mean([d.latency.avg_ms for d in items if d.latency.avg_ms is not None]),
        avg_jitter_ms=_rounded_mean([d.latency.jitter_ms for d in items if d.latency.jitter_ms is not None]),
        active_issues_count=sum(1 for d in alerting if d.health_status in ("offline", "critical", "flapping")),
        ssl_warning_count=sum(1 for d in items for s in d.services if _ssl_warning(s)),
        patch_warning_count=sum(1 for d in items if d.agent and (d.agent.patch_security > 0 or d.agent.reboot_required)),
    )


def _empty_overview(period: str) -> HealthOverviewResponse:
    return HealthOverviewResponse(
        kpis=HealthOverviewKPIs(
            network_health_score=100,
            total_devices=0,
            online_devices=0,
            offline_devices=0,
            flapping_devices=0,
        ),
        devices=[],
        recent_incidents=[],
        period=period,
    )


@router.get("/overview", response_model=HealthOverviewResponse)
async def get_health_overview(
    period: str = Query("24h", pattern="^(24h|7d|30d)$"),
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
) -> HealthOverviewResponse:
    """Fetch complete network health overview including per-device SLA, latency, and incidents."""
    now = datetime.now(UTC)
    window_start, bucket_count = _parse_period_window(period, now)

    # 1. Fetch all visible devices with services and groups
    res_devices = await db.execute(
        select(Device)
        .options(selectinload(Device.services), selectinload(Device.group))
        .where(Device.is_hidden == False)
        .order_by(Device.sort_order, Device.ip)
    )
    devices = res_devices.scalars().all()
    device_ids = [d.id for d in devices]

    if not device_ids:
        return _empty_overview(period)

    # 2. Fetch agent tokens & latest metrics in bulk
    res_tokens = await db.execute(select(AgentToken).where(AgentToken.device_id.in_(device_ids)))
    tokens_by_dev = {t.device_id: t for t in res_tokens.scalars().all()}
    intervals = await load_intervals(db)

    res_metrics = await db.execute(
        select(DeviceMetrics).where(DeviceMetrics.id.in_(
            select(func.max(DeviceMetrics.id)).where(DeviceMetrics.device_id.in_(device_ids)).group_by(DeviceMetrics.device_id)
        ))
    )
    metrics_by_dev = {m.device_id: m for m in res_metrics.scalars().all()}

    # 3. Health history of the window in bulk: raw probes, or hourly/daily rollups for long windows
    samples_by_dev = await load_health_points(
        db, device_ids, window_start.replace(tzinfo=None), now.replace(tzinfo=None)
    )

    # 4. Fetch recent incidents (last 7 days of DeviceHistory for visible devices)
    cutoff_incidents = now.replace(tzinfo=None) - timedelta(days=7)
    res_incidents = await db.execute(
        select(DeviceHistory, Device)
        .join(Device, DeviceHistory.device_id == Device.id)
        .where(
            Device.is_hidden == False,
            DeviceHistory.timestamp >= cutoff_incidents,
        )
        .order_by(DeviceHistory.timestamp.desc())
        .limit(60)
    )
    recent_incidents = _overview_incidents(res_incidents.all(), now)

    # 5. Assemble per-device health models
    device_items: list[DeviceHealthItem] = []
    for dev in devices:
        uptime_stats, latency_stats = _compute_uptime_and_latency(
            dev, samples_by_dev.get(dev.id, []), now, window_start, bucket_count
        )
        service_items = _service_items(dev)
        agent_alerts = _agent_alerts(dev, tokens_by_dev.get(dev.id), metrics_by_dev.get(dev.id), now, intervals.get(dev.id))
        score, status = _calculate_health_score(dev, uptime_stats, latency_stats, service_items, agent_alerts)
        device_items.append(_device_item(dev, score, status, latency_stats, uptime_stats, service_items, agent_alerts))

    return HealthOverviewResponse(
        kpis=_overview_kpis(device_items),
        devices=device_items,
        recent_incidents=recent_incidents,
        period=period
    )


def _downsample(samples: list, limit: int = MAX_DETAIL_POINTS) -> list:
    """At most ``limit`` evenly spread samples, the newest always kept, so 7d/30d charts stay light."""
    if len(samples) <= limit:
        return samples
    step = len(samples) / float(limit)
    return [samples[int(i * step)] for i in range(limit - 1)] + [samples[-1]]


def _sample_point(s, now: datetime) -> HealthSamplePoint:
    return HealthSamplePoint(
        timestamp=ensure_utc(s.timestamp) or now,
        is_online=s.is_online,
        latency_ms=round(s.latency_ms, 2) if s.latency_ms is not None else None,
        probe_type=s.probe_type,
        ports_up=round(s.ports_up),
        ports_total=s.ports_total,
        uptime_pct=s.uptime_pct,
    )


@router.get("/device/{device_id}", response_model=DeviceHealthDetailResponse)
async def get_device_health_detail(
    device_id: int,
    period: str = Query("24h", pattern="^(24h|7d|30d)$"),
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
) -> DeviceHealthDetailResponse:
    """Fetch detailed health telemetry, raw samples, and incident history for a specific device."""
    now = datetime.now(UTC)
    window_start, bucket_count = _parse_period_window(period, now)

    # 1. Fetch device
    res_dev = await db.execute(
        select(Device)
        .options(selectinload(Device.services), selectinload(Device.group))
        .where(Device.id == device_id)
    )
    dev = res_dev.scalar_one_or_none()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")

    # 2. Agent token & metrics
    token_res = await db.execute(select(AgentToken).where(AgentToken.device_id == device_id))
    agent_token = token_res.scalar_one_or_none()

    m_res = await db.execute(
        select(DeviceMetrics)
        .where(DeviceMetrics.device_id == device_id)
        .order_by(DeviceMetrics.timestamp.desc())
        .limit(1)
    )
    latest_metric = m_res.scalar_one_or_none()

    # 3. Health history (raw probes, or hourly/daily rollups for long windows)
    points_by_dev = await load_health_points(
        db, [device_id], window_start.replace(tzinfo=None), now.replace(tzinfo=None)
    )
    samples = points_by_dev.get(device_id, [])

    # 4. Device incidents
    cutoff_incidents = now.replace(tzinfo=None) - timedelta(days=30)
    res_hist = await db.execute(
        select(DeviceHistory)
        .where(DeviceHistory.device_id == device_id, DeviceHistory.timestamp >= cutoff_incidents)
        .order_by(DeviceHistory.timestamp.desc())
        .limit(50)
    )
    incidents = [
        _incident(h, dev, _DETAIL_CRITICAL, now)
        for h in res_hist.scalars().all()
        if not _hidden_while_asleep(dev, h.status)
    ]

    # Compute stats
    uptime_stats, latency_stats = _compute_uptime_and_latency(dev, samples, now, window_start, bucket_count)
    services = _service_items(dev)
    intervals = await load_intervals(db) if (dev.has_agent or agent_token) else {}
    agent_alerts = _agent_alerts(dev, agent_token, latest_metric, now, intervals.get(dev.id))
    score, status = _calculate_health_score(dev, uptime_stats, latency_stats, services, agent_alerts)

    return DeviceHealthDetailResponse(
        device=_device_item(dev, score, status, latency_stats, uptime_stats, services, agent_alerts),
        time_series=[_sample_point(s, now) for s in _downsample(samples)],
        incidents=incidents
    )
