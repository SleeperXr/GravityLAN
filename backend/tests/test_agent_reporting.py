"""The device list says whether each agent still reports, so GravityUI can show "agent silent"."""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.devices import _agent_reporting
from app.models.agent import AgentConfig, AgentToken
from app.models.device import Device
from app.services.cache_service import dashboard_cache

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def _token(**fields) -> AgentToken:
    fields.setdefault("is_active", True)
    fields.setdefault("created_at", NOW - timedelta(days=3))
    return AgentToken(device_id=1, token="t", **fields)


@pytest.mark.parametrize("last_seen, interval, expected", [
    (NOW - timedelta(seconds=30), None, True),     # within the default window (120 s)
    (NOW - timedelta(minutes=5), None, False),     # silent
    (NOW - timedelta(minutes=5), 300, True),       # a slow agent: window 900 s
    (NOW - timedelta(minutes=20), 300, False),
])
def test_reporting_follows_the_agents_own_interval(last_seen, interval, expected):
    assert _agent_reporting(_token(last_seen=last_seen), interval, NOW) is expected


def test_a_revoked_agent_is_not_judged():
    assert _agent_reporting(_token(is_active=False, last_seen=NOW - timedelta(days=1)), None, NOW) is None


def test_an_agent_that_never_reported_is_silent_once_its_first_report_is_due():
    assert _agent_reporting(_token(last_seen=None, created_at=NOW - timedelta(seconds=30)), None, NOW) is None
    assert _agent_reporting(_token(last_seen=None, created_at=NOW - timedelta(hours=1)), None, NOW) is False


def test_naive_timestamps_from_sqlite_count_as_utc():
    naive = (NOW - timedelta(seconds=30)).replace(tzinfo=None)
    assert _agent_reporting(_token(last_seen=naive), None, NOW) is True


@pytest.mark.asyncio
async def test_device_list_carries_last_report_and_reporting(client, db, admin_token):
    dashboard_cache.invalidate_all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    live = Device(ip="192.0.2.20", display_name="live")
    silent = Device(ip="192.0.2.21", display_name="silent")
    slow = Device(ip="192.0.2.22", display_name="slow")
    db.add_all([live, silent, slow])
    await db.flush()
    db.add_all([
        AgentToken(device_id=live.id, token="a", is_active=True, last_seen=now - timedelta(seconds=10)),
        AgentToken(device_id=silent.id, token="b", is_active=True, last_seen=now - timedelta(minutes=10)),
        AgentToken(device_id=slow.id, token="c", is_active=True, last_seen=now - timedelta(minutes=10)),
        AgentConfig(device_id=slow.id, interval=300),
    ])
    await db.commit()

    data = {d["ip"]: d["agent_info"] for d in (await client.get("/api/devices", headers={"Authorization": f"Bearer {admin_token}"})).json()}
    assert data["192.0.2.20"]["reporting"] is True
    assert data["192.0.2.21"]["reporting"] is False and data["192.0.2.21"]["last_report"]
    assert data["192.0.2.22"]["reporting"] is True  # ten minutes is normal for a 300 s interval
    dashboard_cache.invalidate_all()
