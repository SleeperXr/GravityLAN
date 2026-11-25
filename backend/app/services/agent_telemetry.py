"""Agent Telemetry Service — Time-series metrics processing, persistence, and WebSocket broadcasting."""

import asyncio
import hashlib
import hmac
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict

from fastapi import HTTPException, WebSocket
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.models.agent import AgentConfig, AgentToken, DeviceMetrics
from app.services.agent_tokens import find_agent_token, hash_agent_token, new_agent_token
from app.models.device import Device
from app.models.setting import Setting
from app.scanner.utils import ensure_utc
from app.schemas.agent import AgentSummary, GlobalMetricPoint
from app.services.agent_activity import DEFAULT_INTERVAL, has_active_token, is_token_reporting
from app.services.agent_deployer import LATEST_AGENT_VERSION
from app.services.cache_service import dashboard_cache
from app.services.telemetry_query import MetricPoint, metric_point_from_row

logger = logging.getLogger(__name__)

# Global caches for real-time dashboard updates
_latest_metrics: Dict[int, Dict[str, Any]] = {}
_ws_subscribers: Dict[int, set[WebSocket]] = {}
_setting_cache: Dict[str, Any] = {}
_setting_cache_time: datetime = datetime.min.replace(tzinfo=timezone.utc)


def _hash_agent_token(raw_token: str) -> str:
    """Storage form (``sha256:<hex>``) of an agent bearer token."""
    return hash_agent_token(raw_token)


async def _find_and_migrate_agent_token(
    session: AsyncSession,
    raw_token: str,
    device_id: int | None = None,
) -> AgentToken | None:
    """Active AgentToken the raw token authenticates; legacy rows are upgraded to a tagged hash."""
    return await find_agent_token(session, raw_token, device_id)


async def _get_auto_adopt_setting(db: AsyncSession) -> bool:
    """Read the auto-adoption setting with a 5-minute global cache."""
    global _setting_cache_time
    now = datetime.now(timezone.utc)
    if "allow_auto_adopt" not in _setting_cache or (now - _setting_cache_time).total_seconds() > 300:
        adopt_res = await db.execute(select(Setting).where(Setting.key == "agent.allow_auto_adoption"))
        allow_adopt_setting = adopt_res.scalar_one_or_none()
        _setting_cache["allow_auto_adopt"] = allow_adopt_setting.value.lower() == "true" if allow_adopt_setting else False
        _setting_cache_time = now
    return _setting_cache["allow_auto_adopt"]


def _is_device_stale(now: datetime, device: Device, token_obj: AgentToken | None) -> bool:
    """Return True when a device/token is offline or its heartbeat is stale (> 5 min)."""
    if not token_obj:
        return True
    if not device.is_online:
        return True
    if not token_obj.last_seen:
        return True
    last_seen_aware = ensure_utc(token_obj.last_seen)
    return (now - last_seen_aware).total_seconds() > 300


async def _load_device_for_ip(db: AsyncSession, client_ip: str | None, device_id: int) -> Device:
    """The device behind ``client_ip``, which must be the one the agent claims to be (401 otherwise)."""
    if not client_ip:
        raise HTTPException(status_code=401, detail="Invalid token.")

    dev_result = await db.execute(select(Device).where(Device.ip == client_ip))
    device = dev_result.scalar_one_or_none()
    if not device or device.id != device_id:
        raise HTTPException(status_code=401, detail="Invalid token.")
    return device


async def _adopt_token(db: AsyncSession, device: Device, token_obj: AgentToken | None, token: str) -> AgentToken:
    """Make ``token`` the device's active token, creating the AgentToken row when missing."""
    if token_obj:
        token_obj.token = hash_agent_token(token)
        token_obj.pending_token = None
        token_obj.pending_at = None
        token_obj.reset_host_pin()
        token_obj.is_active = True
    else:
        token_obj = AgentToken(device_id=device.id, token=hash_agent_token(token), is_active=True)
        db.add(token_obj)
    await db.commit()
    dashboard_cache.invalidate_all()
    return token_obj


async def _store_pending_token(db: AsyncSession, device: Device, token_obj: AgentToken | None, token: str) -> None:
    """Park ``token`` as pending until an admin adopts it."""
    pending_at = datetime.now(timezone.utc)
    if token_obj:
        token_obj.pending_token = hash_agent_token(token)
        token_obj.pending_at = pending_at
    else:
        # Placeholder until an admin adopts pending_token: random and inactive, so it
        # can never authenticate and leaks nothing of the submitted token.
        db.add(AgentToken(
            device_id=device.id,
            token=new_agent_token()[1],
            is_active=False,
            pending_token=hash_agent_token(token),
            pending_at=pending_at,
        ))
    await db.commit()
    dashboard_cache.invalidate_all()


async def _resolve_token_mismatch(
    db: AsyncSession,
    agent_token: AgentToken | None,
    token: str,
    client_ip: str | None,
    device_id: int,
    allow_auto_adopt: bool,
) -> AgentToken:
    """Recover agent sessions after DB resets / device re-discovery via auto-adoption."""
    if agent_token:
        return agent_token

    device = await _load_device_for_ip(db, client_ip, device_id)

    logger.warning(f"Token mismatch for device {device.id} ({client_ip}). Storing pending_token.")
    token_res = await db.execute(select(AgentToken).where(AgentToken.device_id == device.id))
    token_obj = token_res.scalar_one_or_none()

    if allow_auto_adopt and _is_device_stale(datetime.now(timezone.utc), device, token_obj):
        logger.info(f"Auto-adopting token for device {device.id} ({client_ip}) because device is offline or stale.")
        return await _adopt_token(db, device, token_obj, token)  # Proceed with normal metric persist!

    await _store_pending_token(db, device, token_obj, token)
    raise HTTPException(status_code=401, detail="Invalid token. Manual adoption required.")


async def _verify_or_pin_host_uid(
    db: AsyncSession,
    agent_token: AgentToken,
    incoming_host_uid: str | None,
    client_ip: str | None,
) -> None:
    """Enforce TOFU host-identity pinning for agent reports.

    A token that is not pinned yet takes any report: older agents (< 0.3.18) send no ``host_uid``,
    and the first report carrying one pins it on ``agent_token``.

    A pinned token only takes reports of the pinned host. Another host is parked in
    ``pending_host_uid`` (with the address it reports from) and rejected with HTTP 409, so cloned VMs
    or migrated hosts cannot mix telemetry into the device until an admin confirms them. A report
    without ``host_uid`` is rejected too: whoever holds only the token (and not the host) cannot know
    the pinned value, and would otherwise get around the pin by leaving the field out.
    """
    if not incoming_host_uid:
        if agent_token.host_uid is None:
            return
        logger.warning(
            "Agent report for device %d (from %s) carries no host identity although one is pinned; rejected.",
            agent_token.device_id,
            client_ip or "unknown",
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "This agent token is pinned to a host, but the report carries no host identity. "
                "Use agent 0.3.18 or newer, or issue a new agent configuration for this device."
            ),
        )
    if agent_token.host_uid is None:
        agent_token.host_uid = incoming_host_uid
        agent_token.clear_pending_host()
        return
    if hmac.compare_digest(agent_token.host_uid, incoming_host_uid):
        return

    # The same foreign host reports every interval: only a new host or a new address is written
    new_host = agent_token.pending_host_uid != incoming_host_uid
    if new_host or agent_token.pending_host_ip != client_ip:
        if new_host:
            logger.warning(
                "Agent host UID mismatch for device %d (from %s): parking host %s for manual confirmation.",
                agent_token.device_id,
                client_ip or "unknown",
                host_uid_fingerprint(incoming_host_uid),
            )
            agent_token.pending_host_uid = incoming_host_uid
            agent_token.pending_host_at = datetime.now(timezone.utc)
        agent_token.pending_host_ip = client_ip
        await db.commit()
        dashboard_cache.invalidate_all()
    raise HTTPException(
        status_code=409,
        detail="Agent host identity changed. Confirm the new host in GravityLAN or revoke this agent token.",
    )


def host_uid_fingerprint(host_uid: str | None) -> str | None:
    """The first 12 hex digits of a ``sha256:`` host UID: short enough to read out, to tell hosts apart.

    For display only. The host chooses its whole UID (the server only checks the format), so another
    one that starts with the same 12 digits is easy to make: a confirmation must not rest on this.
    """
    if not host_uid:
        return None
    return host_uid.split(":", 1)[-1][:12]


def host_uid_confirmation(host_uid: str | None) -> str | None:
    """What a confirmation has to name: a value of the whole pending UID, so it changes whenever that does."""
    if not host_uid:
        return None
    return hashlib.sha256(f"gravitylan-host-confirmation:{host_uid}".encode()).hexdigest()[:32]


# (key in the agent's "system" block, AgentToken column, column length)
_OS_FIELDS = (
    ("os", "os_pretty", 255),
    ("os_name", "os_name", 100),
    ("os_version", "os_version", 100),
    ("os_codename", "os_codename", 100),
    ("arch", "os_arch", 50),
    ("kernel", "os_kernel", 100),
)


def _persist_device_metadata(db_token: AgentToken, device: Device, payload: Any) -> None:
    """Update token/device metadata from the agent payload."""
    now = datetime.now(timezone.utc)
    db_token.last_seen = now
    device.is_online = True
    device.missed_scans = 0
    device.last_seen = now

    if db_token.agent_version != payload.agent_version:
        db_token.agent_version = payload.agent_version
    if getattr(db_token, "host_uid", None) is None and getattr(payload, "host_uid", None):
        db_token.host_uid = payload.host_uid

    # Persist OS metadata reported by the agent (e.g. from /etc/os-release); empty values keep the old one
    system = payload.system or {}
    for key, column, limit in _OS_FIELDS:
        if system.get(key):
            setattr(db_token, column, str(system[key])[:limit])
    if not device.has_agent:
        device.has_agent = True
        device.alert_offline = True

    # Clear stale pending token flags since we have a successful report with active token
    if db_token.pending_token is not None:
        db_token.pending_token = None
        db_token.pending_at = None


def _build_metrics_row(db: AsyncSession, effective_device_id: int, payload: Any) -> DeviceMetrics:
    """Create a DeviceMetrics row from the agent payload."""
    metrics = DeviceMetrics(
        device_id=effective_device_id,
        cpu_percent=payload.cpu_percent,
        ram_used_mb=payload.ram.used_mb,
        ram_total_mb=payload.ram.total_mb,
        ram_percent=payload.ram.percent,
        disk_json=json.dumps([d.model_dump() for d in payload.disk]) if payload.disk else None,
        temperature=payload.temperature,
        net_json=json.dumps(payload.network) if payload.network else None,
        patch_available=payload.patches.patch_available if payload.patches else 0,
        patch_security=payload.patches.patch_security if payload.patches else 0,
        patch_manager=payload.patches.patch_manager if payload.patches else None,
        reboot_required=payload.patches.reboot_required if payload.patches else False,
        major_upgrade_available=payload.patches.major_upgrade_available if payload.patches else None,
    )
    db.add(metrics)
    return metrics


def _build_config_payload(agent_config: AgentConfig) -> dict:
    """Serialize the remote agent config dict."""
    return {
        "version": agent_config.version,
        "interval": agent_config.interval,
        "disk_paths": agent_config.disk_paths,
        "enable_temp": agent_config.enable_temp,
        "enable_patch_check": agent_config.enable_patch_check,
        "enable_scanner_relay": getattr(agent_config, "enable_scanner_relay", False),
    }


_PERSIST_ATTEMPTS = 5


async def _load_report_targets(
    db: AsyncSession, token_id: int, device_id: int, client_ip: str | None
) -> tuple[AgentToken | None, Device]:
    """Fresh token + device for this transaction; remaps both by IP if the device was deleted/recreated."""
    db_token = await db.get(AgentToken, token_id)
    device = await db.get(Device, device_id)
    if device:
        return db_token, device

    dev_res = await db.execute(select(Device).where(Device.ip == client_ip))
    device = dev_res.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device mapping lost")
    if db_token:
        db_token.device_id = device.id
    return db_token, device


async def _load_or_create_config(db: AsyncSession, device_id: int) -> AgentConfig:
    """The device's AgentConfig; a default one is created (flushed) on first report."""
    config_res = await db.execute(select(AgentConfig).where(AgentConfig.device_id == device_id))
    agent_config = config_res.scalar_one_or_none()
    if not agent_config:
        agent_config = AgentConfig(device_id=device_id)
        db.add(agent_config)
        await db.flush()
    return agent_config


async def _persist_report_once(
    db: AsyncSession, token_id: int, device_id: int, payload: Any, client_ip: str | None
) -> dict:
    """One transactional attempt of persisting an agent report; returns the config to send back."""
    db_token, device = await _load_report_targets(db, token_id, device_id, client_ip)
    if db_token:
        _persist_device_metadata(db_token, device, payload)
    _build_metrics_row(db, device.id, payload)

    config_to_send = _build_config_payload(await _load_or_create_config(db, device.id))
    await db.commit()
    return config_to_send


async def _persist_agent_report(db: AsyncSession, agent_token: AgentToken, payload: Any, client_ip: str | None) -> dict:
    """Persist the agent report with up to 5 retries on stale/operational DB errors."""
    token_id = agent_token.id
    device_id = agent_token.device_id

    for attempt in range(_PERSIST_ATTEMPTS):
        try:
            return await _persist_report_once(db, token_id, device_id, payload, client_ip)
        except (StaleDataError, OperationalError) as e:
            await db.rollback()
            if attempt == _PERSIST_ATTEMPTS - 1:
                logger.error(f"Agent report persistence failed after {_PERSIST_ATTEMPTS} attempts: {e}")
                raise
            await asyncio.sleep((attempt + 1) * 0.3)

    raise HTTPException(status_code=500, detail="Agent report persistence failed")


def _build_metrics_snapshot(payload: Any, device_id: int) -> dict:
    """Build the WebSocket snapshot dict from a report payload."""
    return {
        "device_id": device_id,
        "cpu_percent": payload.cpu_percent,
        "ram": payload.ram.model_dump(),
        "disk": [d.model_dump() for d in payload.disk],
        "temperature": payload.temperature,
        "network": payload.network,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "patch_available": payload.patches.patch_available if payload.patches else 0,
        "patch_security": payload.patches.patch_security if payload.patches else 0,
        "patch_manager": payload.patches.patch_manager if payload.patches else None,
        "reboot_required": payload.patches.reboot_required if payload.patches else False,
        "major_upgrade_available": payload.patches.major_upgrade_available if payload.patches else None,
    }


async def _broadcast_metrics(payload: Any, device_id: int) -> None:
    """Push the latest snapshot to all subscribed WebSockets, pruning dead links."""
    snapshot = _build_metrics_snapshot(payload, device_id)
    _latest_metrics[device_id] = snapshot

    subscribers = _ws_subscribers.get(device_id)
    if not subscribers:
        return

    dead_links = set()
    # A snapshot: dashboards connect and disconnect (or get closed on revocation) while we await
    for ws in list(subscribers):
        try:
            await ws.send_json({"type": "metrics", "data": snapshot})
        except Exception as e:
            logger.debug(f"Metrics WebSocket error for device {device_id}: {e}")
            dead_links.add(ws)
    subscribers -= dead_links


def downsample_metrics(metrics: list, range_str: str) -> list[dict]:
    """Aggregates and downsamples metrics into buckets to optimize transmission and chart performance.

    ``metrics`` are raw DeviceMetrics rows or MetricPoints (raw rows and hourly/daily
    rollups, see app.services.telemetry_query); averages are weighted by the number
    of agent reports behind each point.
    """
    if not metrics:
        return []
    bucket_seconds = _BUCKET_SECONDS.get(range_str, 900)
    buckets = _bucket_points(metrics, bucket_seconds)
    return [_bucket_snapshot(epoch, buckets[epoch]) for epoch in sorted(buckets)]


# Chart bucket size per range: 5 min, 15 min, 2 h, 6 h
_BUCKET_SECONDS = {"6h": 300, "24h": 900, "7d": 7200, "30d": 21600}


def _bucket_points(metrics: list, bucket_seconds: int) -> dict[int, list[MetricPoint]]:
    """Metric points grouped by the start (epoch seconds) of their bucket; points without a time are dropped."""
    buckets: dict[int, list[MetricPoint]] = {}
    for m in metrics:
        point = m if isinstance(m, MetricPoint) else metric_point_from_row(m)
        ts = ensure_utc(point.timestamp)
        if ts:
            buckets.setdefault((int(ts.timestamp()) // bucket_seconds) * bucket_seconds, []).append(point)
    return buckets


def _bucket_snapshot(epoch: int, points: list[MetricPoint]) -> dict:
    """One chart point: averages weighted by the reports behind each point, the newest disk/net snapshot."""
    weight = sum(p.samples for p in points) or 1

    def avg(attr: str) -> float:
        return sum(getattr(p, attr) * p.samples for p in points) / weight

    temp_weight = sum(p.temp_count for p in points)
    avg_temp = sum(p.temp_avg * p.temp_count for p in points if p.temp_avg is not None) / temp_weight if temp_weight else None
    disk_json = next((p.disk_json for p in reversed(points) if p.disk_json), None)
    net_json = next((p.net_json for p in reversed(points) if p.net_json), None)
    return {
        "cpu_percent": avg("cpu_avg"),
        "ram": {
            "used_mb": int(avg("ram_used_mb_avg")),
            "total_mb": int(avg("ram_total_mb")),
            "percent": avg("ram_percent_avg"),
        },
        "disk": json.loads(disk_json) if disk_json else [],
        "temperature": avg_temp,
        "network": json.loads(net_json) if net_json else {},
        "timestamp": datetime.fromtimestamp(epoch, tz=timezone.utc),
    }


def _is_agent_active(token: AgentToken, now: datetime, interval: int | None = None) -> bool:
    """Active = an authorized token with a report within the window of its interval."""
    return is_token_reporting(token, interval, now)


def _metric_naive_utc(m) -> datetime:
    ts = m.timestamp
    return ensure_utc(ts).replace(tzinfo=None) if getattr(ts, "tzinfo", None) else ts


def _compute_uptime_pct(
    token: AgentToken, now: datetime, cutoff_24h: datetime, device_metrics_24h: list, interval: int | None = None,
) -> float | None:
    """24h agent report coverage (%): received reports vs. expected reports in the observed window.

    ``token.created_at`` marks the start of the token's registration in GravityLAN (not a verified
    host installation timestamp). Measures reporting coverage rather than guaranteed host availability.
    Returns ``None`` when the observation window has not started or holds zero reports.
    """
    now_utc = ensure_utc(now)
    cutoff_utc = ensure_utc(cutoff_24h)
    agent_birth = ensure_utc(token.created_at) or cutoff_utc
    start = max(cutoff_utc, agent_birth)
    end = now_utc
    if end <= start:
        return None

    start_naive = start.replace(tzinfo=None)
    end_naive = end.replace(tzinfo=None)
    day_count = sum(1 for m in device_metrics_24h if start_naive <= _metric_naive_utc(m) < end_naive)
    if day_count == 0:
        return None

    eff_interval = interval if (interval and interval > 0) else DEFAULT_INTERVAL
    expected = (end - start).total_seconds() / eff_interval
    if expected <= 0:
        return None
    return min(100.0, (day_count / expected) * 100.0)


def _compute_uptime_history(
    token: AgentToken, now: datetime, cutoff_24h: datetime, device_metrics_24h: list, interval: int | None = None,
) -> list[float | None]:
    """Hourly agent report coverage over 24 one-hour buckets starting at ``cutoff_24h``.

    Buckets before ``token.created_at``, future buckets at or after ``now``, and buckets without any
    recorded reports return ``None`` (no data) instead of synthetic 100 % or 0 % values. Partial buckets
    (registration mid-hour or a running hour ending at ``now``) scale expected reports to ``end - start``.
    """
    now_utc = ensure_utc(now)
    cutoff_utc = ensure_utc(cutoff_24h)
    agent_birth = ensure_utc(token.created_at) or cutoff_utc
    eff_interval = interval if (interval and interval > 0) else DEFAULT_INTERVAL
    uptime_history: list[float | None] = []
    for h in range(24):
        h_start = cutoff_utc + timedelta(hours=h)
        h_end = h_start + timedelta(hours=1)
        start = max(h_start, agent_birth)
        end = min(h_end, now_utc)
        if end <= start:
            uptime_history.append(None)
            continue

        start_naive = start.replace(tzinfo=None)
        end_naive = end.replace(tzinfo=None)
        h_count = sum(1 for m in device_metrics_24h if start_naive <= _metric_naive_utc(m) < end_naive)
        if h_count == 0:
            uptime_history.append(None)
            continue

        expected = (end - start).total_seconds() / eff_interval
        uptime_history.append(min(100.0, (h_count / expected) * 100.0) if expected > 0 else None)
    return uptime_history


def _build_agent_summary(device: Device, token: AgentToken, last_m: DeviceMetrics | None, m_count: int, is_active: bool, uptime_pct: float | None, uptime_history: list[float | None]) -> AgentSummary:
    """Assemble a single AgentSummary entry from prefetched data."""
    m = last_m or _NO_METRICS
    return AgentSummary(
        device_id=device.id,
        hostname=device.hostname or device.display_name,
        ip=device.ip,
        is_online=is_active,
        agent_version=token.agent_version,
        latest_version=LATEST_AGENT_VERSION,
        os_pretty=token.os_pretty,
        os_name=token.os_name,
        os_version=token.os_version,
        os_codename=token.os_codename,
        os_arch=token.os_arch,
        os_kernel=token.os_kernel,
        last_seen=token.last_seen,
        cpu_usage=m.cpu_percent,
        ram_usage=m.ram_percent,
        temp=m.temperature,
        uptime_pct=uptime_pct,
        uptime_history=uptime_history,
        metrics_count=m_count,
        has_pending_token=bool(token.pending_token),
        pending_at=token.pending_at,
        has_pending_host_uid=bool(getattr(token, "pending_host_uid", None)),
        pending_host_at=getattr(token, "pending_host_at", None),
        pending_host_ip=getattr(token, "pending_host_ip", None),
        pending_host_fingerprint=host_uid_fingerprint(getattr(token, "pending_host_uid", None)),
        pending_host_confirmation=host_uid_confirmation(getattr(token, "pending_host_uid", None)),
        patch_available=m.patch_available,
        patch_security=m.patch_security,
        patch_manager=m.patch_manager,
        reboot_required=m.reboot_required,
        major_upgrade_available=m.major_upgrade_available,
    )


# What an agent summary shows before the agent's first report
_NO_METRICS = SimpleNamespace(
    cpu_percent=0.0, ram_percent=0.0, temperature=None, patch_available=0, patch_security=0,
    patch_manager=None, reboot_required=False, major_upgrade_available=None,
)


def assemble_agents_overview_data(
    device_ids: list[int],
    device_map: dict[int, Device],
    token_map: dict[int, AgentToken],
    all_24h_metrics: list[DeviceMetrics],
    total_count_map: dict[int, int],
    now: datetime,
    cutoff_24h: datetime,
    intervals: dict[int, int] | None = None,
) -> tuple[list[AgentSummary], int, int, int, float, float]:
    """Aggregate metrics and calculate averages for all agent devices in one pass."""
    metrics_by_device: dict[int, list[DeviceMetrics]] = defaultdict(list)
    for m in all_24h_metrics:
        metrics_by_device[m.device_id].append(m)
    intervals = intervals or {}

    agents_list: list[AgentSummary] = []
    authorized_count = 0
    total_metrics_count = 0
    cpu_vals: list[float] = []
    ram_vals: list[float] = []
    active_count = 0

    for device_id in device_ids:
        token = token_map[device_id]
        authorized = has_active_token(token)
        device_metrics_24h = metrics_by_device[device_id] if authorized else []
        last_m = next(iter(device_metrics_24h), None)
        m_count = total_count_map.get(device_id, 0) if authorized else 0

        if authorized:
            authorized_count += 1
            total_metrics_count += m_count

        is_active = _is_agent_active(token, now, intervals.get(device_id))
        if is_active:
            active_count += 1
            if last_m is not None:
                if last_m.cpu_percent is not None:
                    cpu_vals.append(last_m.cpu_percent)
                if last_m.ram_percent is not None:
                    ram_vals.append(last_m.ram_percent)

        interval = intervals.get(device_id)
        if authorized:
            uptime_pct = _compute_uptime_pct(token, now, cutoff_24h, device_metrics_24h, interval)
            uptime_history = _compute_uptime_history(token, now, cutoff_24h, device_metrics_24h, interval)
        else:
            uptime_pct = None
            uptime_history = []
        agents_list.append(
            _build_agent_summary(device_map[device_id], token, last_m, m_count, is_active, uptime_pct, uptime_history)
        )

    avg_cpu = _average(sum(cpu_vals), len(cpu_vals))
    avg_ram = _average(sum(ram_vals), len(ram_vals))
    return agents_list, authorized_count, active_count, total_metrics_count, avg_cpu, avg_ram


def _average(total: float, count: int) -> float:
    """``total / count``, or 0.0 for an empty set."""
    return total / count if count else 0.0


def aggregate_global_metrics_buckets(all_metrics: list) -> list[GlobalMetricPoint]:
    """Group 24h metrics into sorted 15-minute average buckets."""
    buckets: dict[datetime, dict[str, Any]] = {}
    for ts, cpu, ram in all_metrics:
        bucket_ts = ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)
        if bucket_ts not in buckets:
            buckets[bucket_ts] = {"cpu": [], "ram": [], "count": 0}
        buckets[bucket_ts]["cpu"].append(cpu)
        buckets[bucket_ts]["ram"].append(ram)
        buckets[bucket_ts]["count"] += 1

    history_list: list[GlobalMetricPoint] = []
    for b_ts in sorted(buckets.keys()):
        b_data = buckets[b_ts]
        history_list.append(GlobalMetricPoint(
            timestamp=b_ts,
            avg_cpu=sum(b_data["cpu"]) / len(b_data["cpu"]) if b_data["cpu"] else 0.0,
            avg_ram=sum(b_data["ram"]) / len(b_data["ram"]) if b_data["ram"] else 0.0,
            data_points=b_data["count"]
        ))
    return history_list
