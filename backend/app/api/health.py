"""Health summary and historical telemetry API endpoints for GravityLAN."""

import logging
from datetime import UTC, datetime, timedelta

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
    for agent in agents:
        last_seen = ensure_utc(agent.last_seen)
        is_active = bool(agent.is_active and last_seen and (now - last_seen).total_seconds() < 300)
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


def _calculate_health_score(
    dev: Device,
    uptime: UptimeStats,
    latency: LatencyStats,
    services: list[ServiceHealthItem],
    agent: AgentHealthAlerts | None
) -> tuple[int, str]:
    is_alert_enabled = getattr(dev, "alert_offline", True)

    if not is_alert_enabled:
        # Non-24/7 client (e.g. TV, PC, laptop, phone)
        # If it's not online, or has missed scans, or has no current latency, or all services are down:
        is_sleeping = (
            not dev.is_online
            or (dev.missed_scans or 0) > 0
            or latency.current_ms is None
            or (services and all(not s.is_up for s in services))
        )
        if is_sleeping:
            return 100, "standby"

        # If it is currently on and reachable:
        score = 100
        for svc in services:
            if not getattr(svc, "ignore_ssl", False) and svc.ssl_expiry_days is not None:
                if svc.ssl_expiry_days <= 3:
                    score -= 15
                elif svc.ssl_expiry_days <= 14:
                    score -= 5

        if agent and agent.is_active:
            if agent.patch_security > 0:
                score -= 10
            if agent.reboot_required:
                score -= 5

        status = "healthy" if score >= 85 else "degraded"
        return score, status

    # 24/7 Monitored Infrastructure (Servers, Gateways, Switches, APs)
    if not dev.is_online:
        return 0, "offline"

    score = 100

    # Reachability & flapping penalties
    if dev.missed_scans > 0:
        score -= min(30, dev.missed_scans * 15)

    # Uptime SLA penalty
    if uptime.uptime_pct < 99.0:
        score -= int((99.0 - uptime.uptime_pct) * 0.8)

    # High latency penalty
    if latency.avg_ms is not None:
        if latency.avg_ms > 150:
            score -= 15
        elif latency.avg_ms > 60:
            score -= 8

    # Services down or expiring certificates
    for svc in services:
        if not svc.is_up:
            score -= 20
        elif not getattr(svc, "ignore_ssl", False) and svc.ssl_expiry_days is not None:
            if svc.ssl_expiry_days <= 3:
                score -= 15
            elif svc.ssl_expiry_days <= 14:
                score -= 5

    # Agent host warnings
    if agent and agent.is_active:
        if agent.patch_security > 0:
            score -= 10
        if agent.reboot_required:
            score -= 5
        if agent.cpu_percent is not None and agent.cpu_percent > 90:
            score -= 10
        if agent.temperature is not None and agent.temperature > 75:
            score -= 10

    score = max(0, min(100, score))

    if dev.missed_scans > 0:
        status = "flapping"
    elif score < 60 or any(not s.is_up for s in services):
        status = "critical"
    elif score < 85 or (latency.avg_ms and latency.avg_ms > 60):
        status = "degraded"
    else:
        status = "healthy"

    return score, status


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
        return HealthOverviewResponse(
            kpis=HealthOverviewKPIs(
                network_health_score=100,
                total_devices=0,
                online_devices=0,
                offline_devices=0,
                flapping_devices=0
            ),
            devices=[],
            recent_incidents=[],
            period=period
        )

    # 2. Fetch agent tokens & latest metrics in bulk
    res_tokens = await db.execute(select(AgentToken).where(AgentToken.device_id.in_(device_ids)))
    tokens_by_dev = {t.device_id: t for t in res_tokens.scalars().all()}

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
    recent_incidents = []
    for hist, dev in res_incidents.all():
        if not getattr(dev, "alert_offline", True) and hist.status in ("offline", "flapping"):
            continue
        sev = (
            "critical"
            if hist.status in ("offline", "service_down", "down")
            else "warn"
            if hist.status == "flapping"
            else "info"
        )
        recent_incidents.append(HealthIncident(
            id=hist.id,
            device_id=dev.id,
            device_name=dev.display_name or dev.hostname or dev.ip,
            device_ip=dev.ip,
            status=hist.status,
            severity=sev,
            message=hist.message,
            timestamp=ensure_utc(hist.timestamp) or now
        ))
        if len(recent_incidents) >= 40:
            break

    # 5. Assemble per-device health models
    device_items: list[DeviceHealthItem] = []
    total_scores = []
    valid_avg_latencies = []
    valid_avg_jitters = []
    flapping_count = 0
    ssl_warning_count = 0
    patch_warning_count = 0

    for dev in devices:
        dev_samples = samples_by_dev.get(dev.id, [])
        uptime_stats, latency_stats = _compute_uptime_and_latency(dev, dev_samples, now, window_start, bucket_count)

        # Services
        service_items = [
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
        for s in service_items:
            if not s.ignore_ssl and s.ssl_expiry_days is not None and s.ssl_expiry_days <= 14:
                ssl_warning_count += 1

        # Agent alerts
        agent_token = tokens_by_dev.get(dev.id)
        agent_alerts = None
        if dev.has_agent or agent_token:
            m = metrics_by_dev.get(dev.id)
            is_active = bool(agent_token and agent_token.last_seen and (now - ensure_utc(agent_token.last_seen)).total_seconds() < 300)
            agent_alerts = AgentHealthAlerts(
                has_agent=True,
                agent_version=agent_token.agent_version if agent_token else None,
                is_active=is_active,
                cpu_percent=m.cpu_percent if m else None,
                ram_percent=m.ram_percent if m else None,
                temperature=m.temperature if m else None,
                patch_available=m.patch_available if m else 0,
                patch_security=m.patch_security if m else 0,
                reboot_required=m.reboot_required if m else False,
                major_upgrade_available=m.major_upgrade_available if m else None
            )
            if agent_alerts.patch_security > 0 or agent_alerts.reboot_required:
                patch_warning_count += 1

        # Health score & status
        health_score, health_status = _calculate_health_score(dev, uptime_stats, latency_stats, service_items, agent_alerts)
        total_scores.append(health_score)

        if health_status == "flapping":
            flapping_count += 1

        if latency_stats.avg_ms is not None:
            valid_avg_latencies.append(latency_stats.avg_ms)
        if latency_stats.jitter_ms is not None:
            valid_avg_jitters.append(latency_stats.jitter_ms)

        device_items.append(DeviceHealthItem(
            id=dev.id,
            ip=dev.ip,
            display_name=dev.display_name or dev.hostname or dev.ip,
            hostname=dev.hostname,
            device_type=dev.device_type,
            group_id=dev.group_id,
            group_name=dev.group.name if dev.group else None,
            is_online=dev.is_online,
            alert_offline=bool(dev.alert_offline),
            missed_scans=dev.missed_scans or 0,
            health_score=health_score,
            health_status=health_status,
            latency=latency_stats,
            uptime=uptime_stats,
            services=service_items,
            agent=agent_alerts,
            ip_changed_at=ensure_utc(dev.ip_changed_at),
            status_changed_at=ensure_utc(dev.status_changed_at),
            last_seen=ensure_utc(dev.last_seen),
        ))

    # Overall KPIs
    avg_score = round(sum(total_scores) / len(total_scores)) if total_scores else 100
    avg_lat = round(sum(valid_avg_latencies) / len(valid_avg_latencies), 1) if valid_avg_latencies else None
    avg_jit = round(sum(valid_avg_jitters) / len(valid_avg_jitters), 1) if valid_avg_jitters else None
    online_count = sum(1 for d in device_items if d.is_online)
    offline_count = sum(1 for d in device_items if not d.is_online and getattr(d, 'alert_offline', True))

    kpis = HealthOverviewKPIs(
        network_health_score=avg_score,
        total_devices=len(device_items),
        online_devices=online_count,
        offline_devices=offline_count,
        flapping_devices=flapping_count,
        avg_latency_ms=avg_lat,
        avg_jitter_ms=avg_jit,
        active_issues_count=len([
            d for d in device_items
            if d.health_status in ("offline", "critical", "flapping")
            and getattr(d, 'alert_offline', True)
        ]),
        ssl_warning_count=ssl_warning_count,
        patch_warning_count=patch_warning_count,
    )

    return HealthOverviewResponse(
        kpis=kpis,
        devices=device_items,
        recent_incidents=recent_incidents,
        period=period
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
    incidents = []
    for h in res_hist.scalars().all():
        if not getattr(dev, "alert_offline", True) and h.status in ("offline", "flapping"):
            continue
        sev = "critical" if h.status in ("offline", "service_down") else "warn" if h.status == "flapping" else "info"
        incidents.append(HealthIncident(
            id=h.id,
            device_id=dev.id,
            device_name=dev.display_name or dev.hostname or dev.ip,
            device_ip=dev.ip,
            status=h.status,
            severity=sev,
            message=h.message,
            timestamp=ensure_utc(h.timestamp) or now
        ))

    # Compute stats
    uptime_stats, latency_stats = _compute_uptime_and_latency(dev, samples, now, window_start, bucket_count)

    services = [
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

    agent_alerts = None
    if dev.has_agent or agent_token:
        is_active = bool(agent_token and agent_token.last_seen and (now - ensure_utc(agent_token.last_seen)).total_seconds() < 300)
        agent_alerts = AgentHealthAlerts(
            has_agent=True,
            agent_version=agent_token.agent_version if agent_token else None,
            is_active=is_active,
            cpu_percent=latest_metric.cpu_percent if latest_metric else None,
            ram_percent=latest_metric.ram_percent if latest_metric else None,
            temperature=latest_metric.temperature if latest_metric else None,
            patch_available=latest_metric.patch_available if latest_metric else 0,
            patch_security=latest_metric.patch_security if latest_metric else 0,
            reboot_required=latest_metric.reboot_required if latest_metric else False,
            major_upgrade_available=latest_metric.major_upgrade_available if latest_metric else None
        )

    score, status = _calculate_health_score(dev, uptime_stats, latency_stats, services, agent_alerts)

    device_item = DeviceHealthItem(
        id=dev.id,
        ip=dev.ip,
        display_name=dev.display_name or dev.hostname or dev.ip,
        hostname=dev.hostname,
        device_type=dev.device_type,
        group_id=dev.group_id,
        group_name=dev.group.name if dev.group else None,
        is_online=dev.is_online,
        alert_offline=bool(dev.alert_offline),
        missed_scans=dev.missed_scans or 0,
        health_score=score,
        health_status=status,
        latency=latency_stats,
        uptime=uptime_stats,
        services=services,
        agent=agent_alerts,
        ip_changed_at=ensure_utc(dev.ip_changed_at),
        status_changed_at=ensure_utc(dev.status_changed_at),
        last_seen=ensure_utc(dev.last_seen),
    )

    # Downsample time_series points to prevent browser canvas freeze on 7d/30d
    MAX_DETAIL_POINTS = 120
    if len(samples) > MAX_DETAIL_POINTS:
        step = len(samples) / float(MAX_DETAIL_POINTS)
        selected_samples = [samples[int(i * step)] for i in range(MAX_DETAIL_POINTS - 1)]
        selected_samples.append(samples[-1])
    else:
        selected_samples = samples

    time_series = [
        HealthSamplePoint(
            timestamp=ensure_utc(s.timestamp) or now,
            is_online=s.is_online,
            latency_ms=round(s.latency_ms, 2) if s.latency_ms is not None else None,
            probe_type=s.probe_type,
            ports_up=round(s.ports_up),
            ports_total=s.ports_total,
            uptime_pct=s.uptime_pct,
        )
        for s in selected_samples
    ]

    return DeviceHealthDetailResponse(
        device=device_item,
        time_series=time_series,
        incidents=incidents
    )
