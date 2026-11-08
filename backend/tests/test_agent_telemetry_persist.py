"""app/services/agent_telemetry.py: report persistence (retry, device remap) and token-mismatch recovery."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import app.services.agent_telemetry as at
from app.models.agent import AgentConfig, AgentToken, DeviceMetrics
from app.models.device import Device
from app.services.agent_tokens import hash_agent_token


def _payload() -> SimpleNamespace:
    return SimpleNamespace(
        agent_version="1.0.0",
        system={"os": "Debian 12", "arch": "x86_64"},
        cpu_percent=10.0,
        ram=SimpleNamespace(
            used_mb=1,
            total_mb=2,
            percent=50.0,
            model_dump=lambda: {"used_mb": 1, "total_mb": 2, "percent": 50.0},
        ),
        disk=[],
        temperature=None,
        network=None,
        patches=None,
    )


async def _seed_device(db, device_id: int = 1, ip: str = "10.0.0.5", *, online: bool = True) -> Device:
    device = Device(id=device_id, ip=ip, display_name="dev", is_online=online)
    db.add(device)
    await db.commit()
    return device


async def _seed_token(db, device_id: int = 1) -> AgentToken:
    agent_token = AgentToken(device_id=device_id, token="old", is_active=True)
    db.add(agent_token)
    await db.commit()
    return agent_token


# --- _persist_agent_report ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_report_stores_metrics_and_default_config(db):
    await _seed_device(db)
    agent_token = await _seed_token(db)

    config = await at._persist_agent_report(db, agent_token, _payload(), "10.0.0.5")

    assert config["interval"] == (await db.execute(select(AgentConfig))).scalar_one().interval
    assert len((await db.execute(select(DeviceMetrics))).scalars().all()) == 1
    assert (await db.get(AgentToken, agent_token.id)).os_pretty == "Debian 12"


@pytest.mark.asyncio
async def test_persist_report_remaps_token_to_device_with_same_ip(db):
    await _seed_device(db, device_id=1, ip="10.0.0.1")
    await _seed_device(db, device_id=2, ip="10.0.0.5")
    real_token = await _seed_token(db, device_id=1)
    agent_token = SimpleNamespace(id=real_token.id, device_id=99)  # stale view: device 99 no longer exists

    await at._persist_agent_report(db, agent_token, _payload(), "10.0.0.5")

    assert (await db.get(AgentToken, real_token.id)).device_id == 2
    assert (await db.execute(select(DeviceMetrics))).scalar_one().device_id == 2


@pytest.mark.asyncio
async def test_persist_report_unknown_device_is_404(db):
    await _seed_device(db, device_id=1, ip="10.0.0.1")
    real_token = await _seed_token(db, device_id=1)
    agent_token = SimpleNamespace(id=real_token.id, device_id=99)

    with pytest.raises(HTTPException) as exc:
        await at._persist_agent_report(db, agent_token, _payload(), "10.9.9.9")

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_persist_report_retries_operational_errors(db, monkeypatch):
    agent_token = SimpleNamespace(id=1, device_id=1)
    attempts = AsyncMock(side_effect=[OperationalError("s", {}, Exception("locked")), {"ok": True}])
    monkeypatch.setattr(at, "_persist_report_once", attempts)
    monkeypatch.setattr(at.asyncio, "sleep", AsyncMock())
    rollback = AsyncMock()
    monkeypatch.setattr(db, "rollback", rollback)

    assert await at._persist_agent_report(db, agent_token, _payload(), None) == {"ok": True}
    assert attempts.await_count == 2
    assert rollback.await_count == 1


@pytest.mark.asyncio
async def test_persist_report_reraises_after_last_attempt(db, monkeypatch):
    agent_token = SimpleNamespace(id=1, device_id=1)
    attempts = AsyncMock(side_effect=OperationalError("s", {}, Exception("locked")))
    monkeypatch.setattr(at, "_persist_report_once", attempts)
    monkeypatch.setattr(at.asyncio, "sleep", AsyncMock())

    with pytest.raises(OperationalError):
        await at._persist_agent_report(db, agent_token, _payload(), None)

    assert attempts.await_count == at._PERSIST_ATTEMPTS


# --- _resolve_token_mismatch -------------------------------------------------------------

@pytest.mark.asyncio
async def test_mismatch_returns_existing_token(db):
    existing = SimpleNamespace(id=7)
    assert await at._resolve_token_mismatch(db, existing, "t", None, 1, False) is existing


@pytest.mark.asyncio
@pytest.mark.parametrize("client_ip, device_id", [(None, 1), ("10.1.1.1", 1), ("10.0.0.5", 2)])
async def test_mismatch_rejects_unknown_ip_or_other_device(db, client_ip, device_id):
    await _seed_device(db, device_id=1, ip="10.0.0.5")

    with pytest.raises(HTTPException) as exc:
        await at._resolve_token_mismatch(db, None, "t", client_ip, device_id, True)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_mismatch_stores_pending_token_on_fresh_placeholder(db):
    await _seed_device(db)

    with pytest.raises(HTTPException) as exc:
        await at._resolve_token_mismatch(db, None, "new-token", "10.0.0.5", 1, False)

    placeholder = (await db.execute(select(AgentToken))).scalar_one()
    assert exc.value.detail == "Invalid token. Manual adoption required."
    assert placeholder.is_active is False
    assert placeholder.pending_token == hash_agent_token("new-token")
    assert placeholder.token != hash_agent_token("new-token")


@pytest.mark.asyncio
async def test_mismatch_stores_pending_token_on_existing_row_when_device_fresh(db):
    await _seed_device(db)
    existing = await _seed_token(db)
    existing.last_seen = datetime.now(timezone.utc)
    await db.commit()

    with pytest.raises(HTTPException):
        await at._resolve_token_mismatch(db, None, "new-token", "10.0.0.5", 1, True)

    refreshed = await db.get(AgentToken, existing.id)
    assert refreshed.pending_token == hash_agent_token("new-token")
    assert refreshed.pending_at is not None
    assert refreshed.token == "old"


@pytest.mark.asyncio
async def test_mismatch_auto_adopts_stale_device_without_token_row(db):
    await _seed_device(db, online=False)

    adopted = await at._resolve_token_mismatch(db, None, "new-token", "10.0.0.5", 1, True)

    assert adopted.is_active is True
    assert adopted.token == hash_agent_token("new-token")


@pytest.mark.asyncio
async def test_mismatch_auto_adopt_replaces_existing_token_and_clears_pending(db):
    await _seed_device(db, online=False)
    existing = await _seed_token(db)
    existing.pending_token = "stale"
    existing.pending_at = datetime.now(timezone.utc)
    await db.commit()

    adopted = await at._resolve_token_mismatch(db, None, "new-token", "10.0.0.5", 1, True)

    assert adopted.id == existing.id
    assert adopted.token == hash_agent_token("new-token")
    assert adopted.pending_token is None and adopted.pending_at is None


# --- broadcasts, global buckets, and stale helper -----------------------------------------

def test_hash_agent_token_and_is_device_stale_when_last_seen_missing():
    now = datetime.now(timezone.utc)
    device = SimpleNamespace(is_online=True)
    token_no_last_seen = SimpleNamespace(last_seen=None)

    assert at._hash_agent_token("abc") == hash_agent_token("abc")
    assert at._is_device_stale(now, device, token_no_last_seen) is True


@pytest.mark.asyncio
async def test_broadcast_metrics_sends_and_prunes_dead_subscribers(monkeypatch):
    live_ws = AsyncMock()
    dead_ws = AsyncMock()
    dead_ws.send_json.side_effect = RuntimeError("closed")
    subscribers = {live_ws, dead_ws}
    monkeypatch.setitem(at._ws_subscribers, 42, subscribers)

    await at._broadcast_metrics(_payload(), 42)

    assert live_ws.send_json.await_count == 1
    assert subscribers == {live_ws}


def test_downsample_metrics_returns_empty_for_empty_input():
    assert at.downsample_metrics([], "24h") == []


def test_aggregate_global_metrics_buckets_groups_into_15m_windows():
    t0 = datetime(2026, 11, 8, 12, 3, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 8, 12, 14, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 8, 12, 18, tzinfo=timezone.utc)

    points = at.aggregate_global_metrics_buckets([(t2, 30.0, 60.0), (t0, 10.0, 20.0), (t1, 20.0, 40.0)])

    assert len(points) == 2
    assert points[0].timestamp == datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    assert points[0].avg_cpu == 15.0
    assert points[0].avg_ram == 30.0
    assert points[0].data_points == 2
    assert points[1].timestamp == datetime(2026, 11, 8, 12, 15, tzinfo=timezone.utc)
    assert points[1].avg_cpu == 30.0
    assert points[1].avg_ram == 60.0
    assert points[1].data_points == 1

