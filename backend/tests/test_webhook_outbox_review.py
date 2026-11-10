"""Webhook and outbox fixes from the 0.7.0 review: events only after the commit, no retry for deleted
webhooks, removing failed deliveries, bounded list limits and closing the shared HTTP client."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.api.webhooks import is_orphaned
from app.models.webhook import NotificationOutbox, WebhookSubscription
from app.services import webhook_service as ws


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def sent(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(ws, "trigger_webhooks", mock)
    return mock


# --- events after the commit ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_event_waits_for_the_commit(db, sent):
    ws.trigger_webhooks_after_commit(db, "device.offline", {"device_id": 1})
    await asyncio.sleep(0)
    sent.assert_not_awaited()

    await db.commit()
    await asyncio.sleep(0)
    sent.assert_awaited_once_with(event_type="device.offline", data={"device_id": 1})

    # Fired once: a later commit does not send it again
    await db.commit()
    await asyncio.sleep(0)
    assert sent.await_count == 1


@pytest.mark.asyncio
async def test_a_rolled_back_event_is_never_sent(db, sent):
    ws.trigger_webhooks_after_commit(db, "device.offline", {"device_id": 2})
    await db.rollback()
    await db.commit()
    await asyncio.sleep(0)
    sent.assert_not_awaited()


# --- outbox ---------------------------------------------------------------------------------------

def _entry(status="failed", subscription_id=None, service_type="webhook"):
    return NotificationOutbox(
        subscription_id=subscription_id, event_type="device.offline", target_url="http://192.0.2.9/hook",
        service_type=service_type, payload="{}", attempts=3, max_attempts=3, status=status,
        next_attempt_at=datetime(2026, 11, 10),
    )


def test_only_entries_of_a_deleted_webhook_are_orphaned():
    assert is_orphaned(_entry()) is True
    assert is_orphaned(_entry(service_type="ntfy")) is False  # presets never have a subscription
    assert is_orphaned(_entry(subscription_id=5)) is False


@pytest.mark.asyncio
async def test_failed_deliveries_can_be_removed(client, db, auth):
    sub = WebhookSubscription(name="hook", url="http://192.0.2.9/hook", events="device.offline")
    db.add(sub)
    await db.flush()
    db.add_all([_entry("failed", sub.id), _entry("failed"), _entry("pending", sub.id), _entry("delivered", sub.id)])
    await db.commit()

    res = await client.delete("/api/webhooks/outbox/failed", headers=auth)
    assert res.status_code == 200, res.text
    assert res.json()["removed"] == 2
    left = (await db.execute(select(NotificationOutbox.status))).scalars().all()
    assert sorted(left) == ["delivered", "pending"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/webhooks/outbox", "/api/notifications"])
@pytest.mark.parametrize("limit, status", [(-1, 422), (0, 422), (201, 422), (1, 200), (200, 200)])
async def test_list_limits_are_bounded(client, auth, path, limit, status):
    assert (await client.get(f"{path}?limit={limit}", headers=auth)).status_code == status


@pytest.mark.asyncio
async def test_shutdown_closes_the_shared_webhook_client(monkeypatch):
    from app import main
    from app.scanner.scheduler import scheduler

    monkeypatch.setattr(scheduler, "stop", AsyncMock())
    client = await ws._get_client()
    await main._shutdown(type("App", (), {"state": type("State", (), {})()})())
    assert client.is_closed and ws._shared_client is None


@pytest.mark.asyncio
async def test_shutdown_lets_running_deliveries_finish_first(monkeypatch):
    finished = []

    async def delivery(name, delay):
        await asyncio.sleep(delay)
        finished.append(name)
        if name == "first":  # a delivery that starts another while the drain waits
            spawn(ws, "second", 0.01)

    def spawn(module, name, delay):
        task = asyncio.get_running_loop().create_task(delivery(name, delay))
        module._background_webhook_tasks.add(task)
        task.add_done_callback(module._background_webhook_tasks.discard)

    spawn(ws, "first", 0.01)
    assert await ws.drain_webhook_tasks(timeout=2) == 0
    assert finished == ["first", "second"]


@pytest.mark.asyncio
async def test_a_delivery_that_outlasts_the_drain_is_cancelled():
    task = asyncio.get_running_loop().create_task(asyncio.sleep(10))
    ws._background_webhook_tasks.add(task)
    task.add_done_callback(ws._background_webhook_tasks.discard)
    assert await ws.drain_webhook_tasks(timeout=0.05) == 1
    assert task.cancelled()
