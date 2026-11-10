"""app/services/agent_telemetry.py: report metadata, metric downsampling and the agents overview keep their results.

Frozen copies (0.7.0-rc.7) run next to the live functions over seeded random agent payloads, metric series
(raw reports and rollups, naive and aware timestamps, missing temperatures, disk/net snapshots) and overviews.
"""

import json
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.services.agent_telemetry as at
from app.schemas.agent import AgentSummary
from app.scanner.utils import ensure_utc
from app.services.telemetry_query import MetricPoint, metric_point_from_row

UTC = timezone.utc
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


# --- frozen copies -------------------------------------------------------------------------

def _old_persist_device_metadata(db_token, device, payload):
    now = NOW
    db_token.last_seen = now
    device.is_online = True
    device.missed_scans = 0
    device.last_seen = now
    if db_token.agent_version != payload.agent_version:
        db_token.agent_version = payload.agent_version
    system = payload.system or {}
    if system.get("os"):
        db_token.os_pretty = str(system["os"])[:255]
    if system.get("os_name"):
        db_token.os_name = str(system["os_name"])[:100]
    if system.get("os_version"):
        db_token.os_version = str(system["os_version"])[:100]
    if system.get("os_codename"):
        db_token.os_codename = str(system["os_codename"])[:100]
    if system.get("arch"):
        db_token.os_arch = str(system["arch"])[:50]
    if system.get("kernel"):
        db_token.os_kernel = str(system["kernel"])[:100]
    if not device.has_agent:
        device.has_agent = True
        device.alert_offline = True
    if db_token.pending_token is not None:
        db_token.pending_token = None
        db_token.pending_at = None


def _old_downsample(metrics, range_str):
    if not metrics:
        return []
    bucket_seconds = {"6h": 300, "24h": 900, "7d": 7200, "30d": 21600}.get(range_str, 900)
    buckets = {}
    for m in metrics:
        point = m if isinstance(m, MetricPoint) else metric_point_from_row(m)
        ts = ensure_utc(point.timestamp)
        if not ts:
            continue
        bucket_epoch = (int(ts.timestamp()) // bucket_seconds) * bucket_seconds
        buckets.setdefault(bucket_epoch, []).append(point)
    snapshots = []
    for epoch in sorted(buckets.keys()):
        points = buckets[epoch]
        weight = sum(p.samples for p in points) or 1

        def avg(attr):
            return sum(getattr(p, attr) * p.samples for p in points) / weight

        temp_weight = sum(p.temp_count for p in points)
        avg_temp = None
        if temp_weight:
            avg_temp = sum(p.temp_avg * p.temp_count for p in points if p.temp_avg is not None) / temp_weight
        disk_json = next((p.disk_json for p in reversed(points) if p.disk_json), None)
        net_json = next((p.net_json for p in reversed(points) if p.net_json), None)
        snapshots.append({
            "cpu_percent": avg("cpu_avg"),
            "ram": {"used_mb": int(avg("ram_used_mb_avg")), "total_mb": int(avg("ram_total_mb")), "percent": avg("ram_percent_avg")},
            "disk": json.loads(disk_json) if disk_json else [],
            "temperature": avg_temp,
            "network": json.loads(net_json) if net_json else {},
            "timestamp": datetime.fromtimestamp(epoch, tz=UTC),
        })
    return snapshots


def _old_summary(device, token, last_m, m_count, is_active, uptime_pct, uptime_history):
    return AgentSummary(
        device_id=device.id, hostname=device.hostname or device.display_name, ip=device.ip, is_online=is_active,
        agent_version=token.agent_version, latest_version=at.LATEST_AGENT_VERSION, os_pretty=token.os_pretty,
        os_name=token.os_name, os_version=token.os_version, os_codename=token.os_codename, os_arch=token.os_arch,
        os_kernel=token.os_kernel, last_seen=token.last_seen,
        cpu_usage=last_m.cpu_percent if last_m else 0.0, ram_usage=last_m.ram_percent if last_m else 0.0,
        temp=last_m.temperature if last_m else None, uptime_pct=uptime_pct, uptime_history=uptime_history,
        metrics_count=m_count, has_pending_token=bool(token.pending_token), pending_at=token.pending_at,
        patch_available=last_m.patch_available if last_m else 0, patch_security=last_m.patch_security if last_m else 0,
        patch_manager=last_m.patch_manager if last_m else None, reboot_required=last_m.reboot_required if last_m else False,
        major_upgrade_available=last_m.major_upgrade_available if last_m else None,
    )


def _old_assemble(device_ids, device_map, token_map, all_24h_metrics, total_count_map, now, cutoff_24h, intervals=None):
    from collections import defaultdict
    metrics_by_device = defaultdict(list)
    for m in all_24h_metrics:
        metrics_by_device[m.device_id].append(m)
    agents_list, total_metrics_count, total_cpu, total_ram, active_count = [], 0, 0.0, 0.0, 0
    for device_id in device_ids:
        device = device_map[device_id]
        token = token_map[device_id]
        device_metrics_24h = metrics_by_device[device_id]
        last_m = device_metrics_24h[0] if device_metrics_24h else None
        m_count = total_count_map.get(device_id, 0)
        total_metrics_count += m_count
        is_active = at._is_agent_active(token, now, (intervals or {}).get(device_id))
        if is_active:
            active_count += 1
        uptime_pct = at._compute_uptime_pct(token, now, cutoff_24h, device_metrics_24h, (intervals or {}).get(device_id))
        uptime_history = at._compute_uptime_history(token, now, cutoff_24h, device_metrics_24h, (intervals or {}).get(device_id))
        if last_m:
            total_cpu += last_m.cpu_percent
            total_ram += last_m.ram_percent
        agents_list.append(_old_summary(device, token, last_m, m_count, is_active, uptime_pct, uptime_history))
    n = len(agents_list)
    return agents_list, n, active_count, total_metrics_count, (total_cpu / n if n else 0.0), (total_ram / n if n else 0.0)


# --- report metadata -----------------------------------------------------------------------

def _token(rnd):
    return SimpleNamespace(
        last_seen=None, agent_version=rnd.choice([None, "0.6.0", "0.7.0"]), os_pretty="old", os_name=None, os_version=None,
        os_codename=None, os_arch=None, os_kernel=None, pending_token=rnd.choice([None, "hash"]),
        pending_at=rnd.choice([None, NOW]),
    )


@pytest.mark.parametrize("seed", range(120))
def test_report_metadata_matches(seed, monkeypatch):
    rnd = random.Random(seed)

    class FrozenNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(at, "datetime", FrozenNow)
    keys = ["os", "os_name", "os_version", "os_codename", "arch", "kernel"]
    system = None if rnd.random() < 0.2 else {
        k: rnd.choice([None, "", "x" * rnd.randint(1, 300), 42]) for k in keys if rnd.random() < 0.8
    }
    payload = SimpleNamespace(agent_version=rnd.choice(["0.7.0", "0.7.1", None]), system=system)
    token_a = _token(rnd)
    token_b = SimpleNamespace(**vars(token_a))
    has_agent = rnd.random() < 0.5
    dev_a = SimpleNamespace(is_online=False, missed_scans=3, last_seen=None, has_agent=has_agent, alert_offline=False)
    dev_b = SimpleNamespace(**vars(dev_a))

    _old_persist_device_metadata(token_a, dev_a, payload)
    at._persist_device_metadata(token_b, dev_b, payload)
    assert vars(token_b) == vars(token_a)
    assert vars(dev_b) == vars(dev_a)


# --- downsampling ----------------------------------------------------------------------------

def _metrics(rnd):
    out = []
    t = NOW - timedelta(days=rnd.choice([1, 7, 30]))
    for _ in range(rnd.randint(0, 80)):
        t += timedelta(minutes=rnd.choice([1, 7, 30, 200]))
        stamp = t.replace(tzinfo=None) if rnd.random() < 0.5 else t
        disk = json.dumps([{"path": "/", "percent": rnd.randint(1, 99)}]) if rnd.random() < 0.6 else None
        net = json.dumps({"eth0": {"rx": rnd.randint(1, 1000)}}) if rnd.random() < 0.5 else None
        if rnd.random() < 0.5:
            temp = rnd.choice([None, rnd.uniform(30, 90)])
            out.append(SimpleNamespace(timestamp=stamp, cpu_percent=rnd.uniform(0, 100), ram_percent=rnd.uniform(0, 100),
                                       ram_used_mb=rnd.randint(100, 16000), ram_total_mb=16384, temperature=temp,
                                       disk_json=disk, net_json=net))
        else:
            samples = rnd.randint(1, 30)
            temp_count = rnd.randint(0, samples)
            out.append(MetricPoint(
                timestamp=stamp, samples=samples, cpu_avg=rnd.uniform(0, 100), cpu_max=100.0,
                ram_percent_avg=rnd.uniform(0, 100), ram_percent_max=100.0, ram_used_mb_avg=rnd.uniform(100, 16000),
                ram_total_mb=16384, temp_count=temp_count, temp_avg=rnd.uniform(30, 90) if temp_count else None,
                temp_max=None, disk_json=disk, net_json=net, is_raw=False,
            ))
    return out


@pytest.mark.parametrize("seed", range(120))
def test_downsampling_matches(seed):
    rnd = random.Random(seed)
    metrics = _metrics(rnd)
    for range_str in ("6h", "24h", "7d", "30d", "bogus"):
        assert at.downsample_metrics(metrics, range_str) == _old_downsample(metrics, range_str)


# --- overview ---------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(80))
def test_agents_overview_matches(seed):
    rnd = random.Random(seed)
    cutoff = NOW - timedelta(hours=24)
    ids = list(range(1, rnd.randint(1, 8)))
    devices = {i: SimpleNamespace(id=i, hostname=rnd.choice([None, f"h{i}"]), display_name=f"d{i}", ip=f"10.0.0.{i}") for i in ids}
    tokens = {i: SimpleNamespace(
        agent_version="0.7.0", os_pretty=None, os_name="debian", os_version="12", os_codename=None, os_arch="x86_64",
        os_kernel=None, last_seen=(NOW - timedelta(seconds=rnd.choice([10, 200, 4000]))).replace(tzinfo=None),
        created_at=rnd.choice([None, (NOW - timedelta(hours=3)).replace(tzinfo=None), (NOW - timedelta(days=9)).replace(tzinfo=None)]),
        pending_token=rnd.choice([None, "", "x"]), pending_at=None,
    ) for i in ids}
    metrics = []
    for i in ids:
        for k in range(rnd.randint(0, 6)):
            metrics.append(SimpleNamespace(
                device_id=i, timestamp=(NOW - timedelta(minutes=10 * k + 1)).replace(tzinfo=None),
                cpu_percent=rnd.uniform(0, 100), ram_percent=rnd.uniform(0, 100), temperature=rnd.choice([None, 55.0]),
                patch_available=rnd.randint(0, 5), patch_security=rnd.randint(0, 2), patch_manager=rnd.choice([None, "apt"]),
                reboot_required=rnd.random() < 0.3, major_upgrade_available=rnd.choice([None, "24.04"]),
            ))
    counts = {i: rnd.randint(0, 500) for i in ids if rnd.random() < 0.8}
    intervals = rnd.choice([None, {ids[0]: 300} if ids else {}])
    assert at.assemble_agents_overview_data(ids, devices, tokens, metrics, counts, NOW, cutoff, intervals) == \
        _old_assemble(ids, devices, tokens, metrics, counts, NOW, cutoff, intervals)
