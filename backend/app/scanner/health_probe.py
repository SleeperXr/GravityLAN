"""Network & Device Health Telemetry Collector.

Periodically measures round-trip latency, service port response times, and SSL certificate
validity for every monitored device, persisting time-series samples for historical dashboards.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models.agent import AgentToken
from app.models.device import Device, DeviceHealthSample
from app.scanner.presence import (
    FALLBACK_PROBE_PORTS,
    get_offline_threshold,
    register_miss,
    register_seen,
)
from app.scanner.sync import commit_or_discard
from app.scanner.utils import (
    check_ssl_expiry_days,
    ensure_utc,
    measure_ping_latency_ms,
    measure_tcp_latency_ms,
)
from app.services.agent_activity import load_intervals, stale_window
from app.services.mac_observations import open_conflict_device_ids
from app.services.cache_service import dashboard_cache, topology_cache

logger = logging.getLogger(__name__)

# Concurrency limit for background latency/health probes
MAX_PROBE_CONCURRENCY = 15
SERVICE_PROBE_TIMEOUT = 0.8
SERVICE_RETRY_TIMEOUT = 2.0


async def _probe_single_service(
    ip: str, hostname: str | None, svc, now: datetime
) -> tuple[int, float | None, int | None, bool]:
    """Probe a single service port for TCP RTT and (every 6h) SSL certificate expiry."""
    rtt = await measure_tcp_latency_ms(ip, svc.port, timeout=SERVICE_PROBE_TIMEOUT)
    if rtt is None:
        # One slow answer (a busy NAS, a sleeping disk) is no outage: a second, more patient try decides
        rtt = await measure_tcp_latency_ms(ip, svc.port, timeout=SERVICE_RETRY_TIMEOUT)
    ssl_days = None
    ssl_checked = False

    if rtt is not None and not getattr(svc, "ignore_ssl", False):
        is_https = svc.protocol.lower() == "https" or svc.port in (443, 8443)
        needs_ssl_check = (
            is_https
            and (
                svc.ssl_checked_at is None
                or (
                    now - svc.ssl_checked_at.replace(tzinfo=UTC)
                    if svc.ssl_checked_at.tzinfo is None
                    else (now - svc.ssl_checked_at)
                ).total_seconds()
                > 21600
            )
        )
        if needs_ssl_check:
            ssl_days = await check_ssl_expiry_days(ip, svc.port, hostname, timeout=2.0)
            ssl_checked = True

    return svc.id, rtt, ssl_days, ssl_checked


async def _probe_single_device(
    dev: Device, now: datetime, semaphore: asyncio.Semaphore
) -> tuple[DeviceHealthSample, dict[int, tuple[float | None, int | None, bool]]]:
    """Probe a single device for latency, service responsiveness, and SSL expiry."""
    async with semaphore:
        # 1. Primary probe: ICMP Ping RTT
        ping_rtt = await measure_ping_latency_ms(dev.ip, timeout=0.8)

        # 2. Check each configured service concurrently
        service_results: dict[int, tuple[float | None, int | None, bool]] = {}
        ports_up = 0
        ports_total = len(dev.services)
        service_rtts: list[float] = []

        if dev.services:
            svc_probes = await asyncio.gather(
                *(_probe_single_service(dev.ip, dev.hostname, svc, now) for svc in dev.services)
            )
            for svc_id, rtt, ssl_days, ssl_checked in svc_probes:
                if rtt is not None:
                    ports_up += 1
                    service_rtts.append(rtt)
                service_results[svc_id] = (rtt, ssl_days, ssl_checked)

        # 3. Determine overall latency and probe method
        if ping_rtt is not None:
            latency_ms = ping_rtt
            probe_type = "icmp"
            is_online = True
        elif service_rtts:
            latency_ms = min(service_rtts)
            probe_type = "tcp"
            is_online = True
        elif ports_total == 0:
            # Fallback probe for devices without services (SSH, Web, etc.)
            tcp_rtts = await asyncio.gather(
                *(measure_tcp_latency_ms(dev.ip, p, timeout=0.5) for p in FALLBACK_PROBE_PORTS)
            )
            alive_rtts = [r for r in tcp_rtts if r is not None]
            if alive_rtts:
                latency_ms = min(alive_rtts)
                probe_type = "tcp"
                is_online = True
            else:
                latency_ms = None
                probe_type = None
                is_online = False
        else:
            latency_ms = None
            probe_type = None
            is_online = False

        sample = DeviceHealthSample(
            device_id=dev.id,
            timestamp=now.replace(tzinfo=None),
            is_online=is_online,
            latency_ms=latency_ms,
            probe_type=probe_type,
            ports_up=ports_up,
            ports_total=ports_total,
        )

        return sample, service_results


async def _mark_failed_services(devices: list[Device], now: datetime, semaphore: asyncio.Semaphore) -> int:
    """Probe the services of devices with an open MAC conflict and mark the ones that fail as down.

    A port that answers may be the other box's, so a success changes nothing. A port that does not
    answer is down for everyone who uses the address, whichever box holds it right now: hiding that
    while the conflict is open left a real outage invisible. Returns the number of failed services,
    whose state or telemetry changed and must be committed.
    """
    async def probe(dev: Device):
        async with semaphore:
            return dev, await asyncio.gather(
                *(_probe_single_service(dev.ip, dev.hostname, svc, now) for svc in dev.services),
                return_exceptions=True,
            )

    marked = 0
    for result in await asyncio.gather(*(probe(dev) for dev in devices), return_exceptions=True):
        if isinstance(result, BaseException):
            logger.debug("Service probe error on a device with a MAC conflict: %s", result)
            continue
        dev, svc_results = result
        failed = {r[0] for r in svc_results if not isinstance(r, BaseException) and r[1] is None}
        for svc in dev.services:
            if svc.id in failed:
                svc.latency_ms = None
                svc.last_checked = now
                svc.is_up = False
                marked += 1
    return marked


async def run_health_probe_pass() -> int:
    """Execute a single network-wide health and latency probing pass.

    Returns the number of devices sampled.
    """
    now = datetime.now(UTC)

    async with async_session() as db:
        res = await db.execute(
            select(Device)
            .options(selectinload(Device.services))
            .where(Device.is_hidden == False, Device.ip_placeholder == False)
        )
        devices = res.scalars().all()
        if not devices:
            return 0

        semaphore = asyncio.Semaphore(MAX_PROBE_CONCURRENCY)
        offline_threshold = await get_offline_threshold(db)

        device_ids = [d.id for d in devices]
        res_tokens = await db.execute(
            select(AgentToken).where(
                AgentToken.device_id.in_(device_ids),
                AgentToken.is_active.is_(True),
            )
        )
        tokens_by_dev = {t.device_id: t for t in res_tokens.scalars().all()}
        intervals = await load_intervals(db)
        conflict_ids = await open_conflict_device_ids(db, device_ids)
        # Devices with an open MAC conflict cannot be confirmed by L3 probes alone: they get no
        # presence change and no health sample, so a foreign box at the IP neither wakes the device
        # nor writes false-positive samples (normal L3 devices without conflict continue).
        probe_devices = [dev for dev in devices if dev.id not in conflict_ids]
        conflicted = [dev for dev in devices if dev.id in conflict_ids and dev.services]
        services_failed = await _mark_failed_services(conflicted, now, semaphore) if conflicted else 0
        if not probe_devices:
            if services_failed:
                outcome = await commit_or_discard(db)
                if outcome == "ok":
                    dashboard_cache.invalidate_all()
            return 0

        # Run probes concurrently in batches
        tasks = [_probe_single_device(dev, now, semaphore) for dev in probe_devices]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        samples_to_add = []
        for dev, result in zip(probe_devices, results):
            if isinstance(result, Exception):
                logger.debug(f"Health probe error for {dev.ip}: {result}")
                continue

            sample, svc_results = result
            samples_to_add.append(sample)

            # Update services telemetry first so service state reflects the latest probe
            for svc in dev.services:
                if svc.id in svc_results:
                    rtt, ssl_days, ssl_checked = svc_results[svc.id]
                    svc.latency_ms = rtt
                    svc.last_checked = now
                    svc.is_up = rtt is not None
                    if ssl_checked:
                        svc.ssl_expiry_days = ssl_days
                        svc.ssl_checked_at = now

            if sample.is_online:
                dev.last_seen = now
                register_seen(dev)
            else:
                token = tokens_by_dev.get(dev.id)
                has_agent = token is not None
                agent_last_seen = ensure_utc(token.last_seen) if token and token.last_seen else None
                agent_stale = not agent_last_seen or (now - agent_last_seen).total_seconds() > stale_window(intervals.get(dev.id))

                if has_agent and agent_stale:
                    # Both independent channels (ICMP/TCP probe + 30s agent heartbeat) confirm offline
                    dev.missed_scans = max(dev.missed_scans or 0, offline_threshold - 1)
                    await register_miss(dev, db, offline_threshold)
                elif dev.services and (not has_agent or agent_stale):
                    # Devices with services are skipped by planner.py (_cleanup_devices);
                    # since ICMP and all configured service TCP ports failed here, count the miss.
                    await register_miss(dev, db, offline_threshold)

        db.add_all(samples_to_add)
        outcome = await commit_or_discard(db)
        if outcome != "ok":
            # The rollback dropped this pass's samples and state changes; the next pass probes again
            logger.warning("Health probe pass not saved (%s): %d samples dropped", outcome, len(samples_to_add))
            return 0
        dashboard_cache.invalidate_all()
        topology_cache.invalidate()

        logger.debug(f"Health probe pass completed: {len(samples_to_add)} devices sampled")
        return len(samples_to_add)
