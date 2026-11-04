"""An agent counts as active relative to its own reporting interval."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from app.models.agent import AgentConfig, AgentToken
from app.models.device import Device, Service
from app.scanner import health_probe as hp_mod
from app.services.agent_activity import active_window, load_intervals, stale_window
from app.services.agent_telemetry import _is_agent_active

HEADERS = {"Authorization": "Bearer test-admin-token-12345"}


@pytest.mark.parametrize(
    ("interval", "active", "stale"),
    [(None, 120, 75), (5, 120, 75), (30, 120, 75), (60, 180, 150), (300, 900, 750)],
)
def test_windows_follow_the_interval(interval, active, stale):
    assert active_window(interval) == active
    assert stale_window(interval) == stale


def test_slow_agent_is_active_between_two_reports():
    now = datetime.now(UTC)
    token = AgentToken(device_id=1, token="t", last_seen=now - timedelta(seconds=280))

    assert _is_agent_active(token, now, 300) is True
    assert _is_agent_active(token, now, 30) is False


async def _agent_device(db, interval: int, seen_ago: timedelta) -> Device:
    dev = Device(ip="10.0.0.9", display_name="Slow", device_type="server", is_online=True, has_agent=True, alert_offline=True)
    db.add(dev)
    await db.commit()
    db.add_all([
        Service(device_id=dev.id, name="SSH", protocol="ssh", port=22, is_up=True),
        AgentToken(device_id=dev.id, token="tok-slow", is_active=True, last_seen=datetime.now(UTC) - seen_ago),
        AgentConfig(device_id=dev.id, interval=interval),
    ])
    await db.commit()
    return dev


@pytest.mark.asyncio
async def test_load_intervals(db):
    dev = await _agent_device(db, 300, timedelta(seconds=10))

    assert await load_intervals(db) == {dev.id: 300}


@pytest.mark.asyncio
async def test_probe_does_not_call_a_slow_agent_offline_between_reports(monkeypatch, db):
    @asynccontextmanager
    async def fake_session():
        yield db

    async def no_answer(*_args, **_kwargs):
        return None

    monkeypatch.setattr(hp_mod, "async_session", fake_session)
    monkeypatch.setattr(hp_mod, "measure_ping_latency_ms", no_answer)
    monkeypatch.setattr(hp_mod, "measure_tcp_latency_ms", no_answer)
    dev = await _agent_device(db, 300, timedelta(seconds=280))

    await hp_mod.run_health_probe_pass()
    await db.refresh(dev)

    assert dev.is_online is True
