"""The device health score (app/api/health.py _calculate_health_score).

The refactor that split the function into helpers had to keep every result. A frozen copy of the
function as it was before is checked against the current one over a grid of inputs; the examples
below it say in words what the score means.
"""

import itertools
from types import SimpleNamespace

from app.api.health import _calculate_health_score
from app.schemas.health import AgentHealthAlerts, LatencyStats, ServiceHealthItem, UptimeStats


def _reference_score(dev, uptime, latency, services, agent):
    """_calculate_health_score as of 0.7.0-rc.7, unchanged."""
    is_alert_enabled = getattr(dev, "alert_offline", True)

    if not is_alert_enabled:
        is_sleeping = (
            not dev.is_online
            or (dev.missed_scans or 0) > 0
            or latency.current_ms is None
            or (services and all(not s.is_up for s in services))
        )
        if is_sleeping:
            return 100, "standby"

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

    if not dev.is_online:
        return 0, "offline"

    score = 100

    if dev.missed_scans > 0:
        score -= min(30, dev.missed_scans * 15)

    if uptime.uptime_pct < 99.0:
        score -= int((99.0 - uptime.uptime_pct) * 0.8)

    if latency.avg_ms is not None:
        if latency.avg_ms > 150:
            score -= 15
        elif latency.avg_ms > 60:
            score -= 8

    for svc in services:
        if not svc.is_up:
            score -= 20
        elif not getattr(svc, "ignore_ssl", False) and svc.ssl_expiry_days is not None:
            if svc.ssl_expiry_days <= 3:
                score -= 15
            elif svc.ssl_expiry_days <= 14:
                score -= 5

    if agent and agent.has_agent:
        if not agent.is_active:
            if latency.current_ms is None and (not services or all(not s.is_up for s in services)):
                return 0, "offline"
            score -= 35
        else:
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
    elif score < 60 or any(not s.is_up for s in services) or (agent and agent.has_agent and not agent.is_active):
        status = "critical"
    elif score < 85 or (latency.avg_ms and latency.avg_ms > 60):
        status = "degraded"
    else:
        status = "healthy"

    return score, status


def _svc(up=True, days=None, ignore=False):
    return ServiceHealthItem(id=1, name="s", protocol="https", port=443, is_up=up, ssl_expiry_days=days, ignore_ssl=ignore)


DEVICES = [
    SimpleNamespace(alert_offline=alert, is_online=online, missed_scans=missed)
    for alert, online, missed in itertools.product([True, False], [True, False], [0, 1, 3, None])
] + [SimpleNamespace(is_online=True, missed_scans=0)]  # no alert_offline attribute: counts as monitored

UPTIMES = [UptimeStats(uptime_pct=p) for p in (100.0, 99.0, 98.9, 50.0, 0.0)]

LATENCIES = [
    LatencyStats(current_ms=current, avg_ms=avg)
    for current, avg in itertools.product([None, 5.0], [None, 0.0, 30.0, 60.0, 61.0, 150.0, 151.0])
]

SERVICES = [
    [],
    [_svc()],
    [_svc(up=False)],
    [_svc(days=3)],
    [_svc(days=4)],
    [_svc(days=14)],
    [_svc(days=15)],
    [_svc(days=2, ignore=True)],
    [_svc(up=False, days=2)],
    [_svc(), _svc(up=False)],
    [_svc(up=False), _svc(up=False)],
    [_svc(days=1), _svc(days=10), _svc(days=1)],
]

AGENTS = [
    None,
    AgentHealthAlerts(has_agent=False),
    AgentHealthAlerts(has_agent=True, is_active=False),
    AgentHealthAlerts(has_agent=False, is_active=True, patch_security=2),
    AgentHealthAlerts(has_agent=True, is_active=True),
    AgentHealthAlerts(has_agent=True, is_active=True, patch_security=1, reboot_required=True),
    AgentHealthAlerts(has_agent=True, is_active=True, cpu_percent=90.0, temperature=75.0),
    AgentHealthAlerts(has_agent=True, is_active=True, cpu_percent=95.0, temperature=80.0),
]


def _outcome(fn, *args):
    try:
        return fn(*args)
    except Exception as exc:  # the old function raised on missed_scans=None; the new one must too
        return type(exc)


def test_every_input_scores_as_before():
    cases = itertools.product(DEVICES, UPTIMES, LATENCIES, SERVICES, AGENTS)
    mismatches = []
    count = 0
    for case in cases:
        count += 1
        before, now = _outcome(_reference_score, *case), _outcome(_calculate_health_score, *case)
        if before != now:
            mismatches.append((case, before, now))
    assert count > 40_000
    assert mismatches[:3] == []


# --- what the score means ------------------------------------------------------

def _dev(alert=True, online=True, missed=0):
    return SimpleNamespace(alert_offline=alert, is_online=online, missed_scans=missed)


def test_a_device_that_may_sleep_is_standby_when_off_and_rated_on_certificates_and_patches_when_on():
    up = LatencyStats(current_ms=4.0)
    assert _calculate_health_score(_dev(alert=False, online=False), UptimeStats(), up, [], None) == (100, "standby")

    agent = AgentHealthAlerts(has_agent=True, is_active=True, patch_security=3)
    assert _calculate_health_score(_dev(alert=False), UptimeStats(), up, [_svc(days=2)], agent) == (75, "degraded")


def test_a_monitored_device_loses_points_per_problem():
    assert _calculate_health_score(_dev(online=False), UptimeStats(), LatencyStats(), [], None) == (0, "offline")
    assert _calculate_health_score(_dev(), UptimeStats(), LatencyStats(avg_ms=5.0), [_svc()], None) == (100, "healthy")
    # one service down (-20) and high latency (-8)
    assert _calculate_health_score(
        _dev(), UptimeStats(), LatencyStats(avg_ms=70.0), [_svc(), _svc(up=False)], None
    ) == (72, "critical")
    # a silent agent with nothing else answering means the host is gone
    silent = AgentHealthAlerts(has_agent=True, is_active=False)
    assert _calculate_health_score(_dev(), UptimeStats(), LatencyStats(), [], silent) == (0, "offline")
