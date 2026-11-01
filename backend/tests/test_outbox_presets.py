"""Tests for Notification Outbox and Service Presets (ntfy, Gotify, Webhooks)."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from app.models.webhook import NotificationOutbox, WebhookSubscription
from app.services.secret_vault import vault
from app.services.webhook_service import (
    deliver_pending_outbox,
    format_event_notification,
    prepare_request_for_service,
    trigger_webhooks,
)


def test_format_event_notification_offline():
    title, msg, prio, tags = format_event_notification("device.offline", {"display_name": "Switch 1", "ip": "10.0.0.1"})
    assert "Device Offline" in title
    assert "Switch 1" in msg
    assert prio == 8
    assert "skull" in tags


def test_format_event_notification_new_device():
    title, msg, prio, tags = format_event_notification("new_device", {"hostname": "nas.local", "ip": "192.168.1.10", "mac": "aa:bb:cc:dd:ee:ff"})
    assert "New Device Discovered" in title
    assert "nas.local" in msg
    assert "192.168.1.10" in msg
    assert prio == 5
    assert "sparkles" in tags


def test_prepare_request_for_ntfy():
    url = "https://ntfy.example.com/lan-alerts"
    eff_url, headers, body = prepare_request_for_service(
        "ntfy", url, "secret-token", "device.offline", {"display_name": "Server", "ip": "192.168.1.5"}
    )
    assert eff_url == url
    assert headers["Authorization"] == "Bearer secret-token"
    assert headers["Title"] == "GravityLAN: Device Offline"
    assert headers["Priority"] == "high"
    assert "skull" in headers["Tags"]
    assert isinstance(body, bytes)
    assert b"Server" in body


def test_prepare_request_for_gotify():
    url = "https://gotify.example.com"
    eff_url, headers, body = prepare_request_for_service(
        "gotify", url, "app-token-123", "device.online", {"display_name": "Router", "ip": "192.168.1.1"}
    )
    assert eff_url == "https://gotify.example.com/message"
    assert headers["X-Gotify-Key"] == "app-token-123"
    assert isinstance(body, dict)
    assert body["title"] == "GravityLAN: Device Online"
    assert body["priority"] == 5


def test_prepare_request_for_webhook():
    url = "https://homeassistant.local/api/webhook/grav"
    eff_url, headers, body = prepare_request_for_service(
        "webhook", url, "bearer-xyz", "device.ip_changed", {"old_ip": "10.0.0.2", "new_ip": "10.0.0.3"}
    )
    assert eff_url == url
    assert headers["Authorization"] == "Bearer bearer-xyz"
    assert isinstance(body, dict)
    assert body["event"] == "device.ip_changed"
    assert body["data"]["old_ip"] == "10.0.0.2"


@pytest.mark.asyncio
async def test_outbox_successful_delivery(db):
    sub = WebhookSubscription(
        name="Test ntfy",
        url="https://ntfy.example.com/topic",
        service_type="ntfy",
        encrypted_token=vault.encrypt("my-ntfy-token"),
        events="device.offline",
        is_active=True,
    )
    db.add(sub)
    await db.flush()

    outbox = NotificationOutbox(
        subscription_id=sub.id,
        event_type="device.offline",
        target_url=sub.url,
        service_type=sub.service_type,
        encrypted_token=sub.encrypted_token,
        payload=json.dumps({"display_name": "Printer", "ip": "192.168.1.50"}),
        attempts=0,
        max_attempts=3,
        status="pending",
        next_attempt_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(outbox)
    await db.commit()

    mock_resp = httpx.Response(200, request=httpx.Request("POST", sub.url), text="OK")
    with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_resp)) as mock_post:
        delivered = await deliver_pending_outbox(db)
        assert delivered == 1
        assert mock_post.called

    await db.refresh(outbox)
    assert outbox.status == "delivered"
    assert outbox.attempts == 1
    assert outbox.delivered_at is not None
    assert outbox.last_error is None


@pytest.mark.asyncio
async def test_outbox_retry_up_to_max_attempts(db):
    sub = WebhookSubscription(
        name="Test Gotify",
        url="https://gotify.example.com/message",
        service_type="gotify",
        events="device.offline",
        is_active=True,
    )
    db.add(sub)
    await db.flush()

    outbox = NotificationOutbox(
        subscription_id=sub.id,
        event_type="device.offline",
        target_url=sub.url,
        service_type="gotify",
        payload=json.dumps({"ip": "10.0.0.5"}),
        attempts=0,
        max_attempts=3,
        status="pending",
        next_attempt_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(outbox)
    await db.commit()

    mock_fail = httpx.Response(500, request=httpx.Request("POST", sub.url), text="Server Error")

    # Attempt 1 -> fails, remains pending with backoff
    with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_fail)):
        delivered = await deliver_pending_outbox(db)
        assert delivered == 0

    await db.refresh(outbox)
    assert outbox.status == "pending"
    assert outbox.attempts == 1
    assert "HTTP 500" in outbox.last_error
    next_at = outbox.next_attempt_at.replace(tzinfo=timezone.utc) if outbox.next_attempt_at.tzinfo is None else outbox.next_attempt_at
    assert outbox.next_attempt_at > datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)

    # Force next attempt time to now
    outbox.next_attempt_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    # Attempt 2 -> fails, remains pending
    with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_fail)):
        delivered = await deliver_pending_outbox(db)
        assert delivered == 0

    await db.refresh(outbox)
    assert outbox.status == "pending"
    assert outbox.attempts == 2

    # Force next attempt time to now
    outbox.next_attempt_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    # Attempt 3 -> fails, max attempts reached -> status = 'failed'
    with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_fail)):
        delivered = await deliver_pending_outbox(db)
        assert delivered == 0

    await db.refresh(outbox)
    assert outbox.status == "failed"
    assert outbox.attempts == 3


@pytest.mark.asyncio
async def test_blocked_target_fails_outbox_immediately(db):
    outbox = NotificationOutbox(
        event_type="device.offline",
        target_url="http://127.0.0.1:8080/hook",
        service_type="webhook",
        payload="{}",
        attempts=0,
        max_attempts=3,
        status="pending",
        next_attempt_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(outbox)
    await db.commit()

    delivered = await deliver_pending_outbox(db)
    assert delivered == 0

    await db.refresh(outbox)
    assert outbox.status == "failed"
    assert "Blocked target" in (outbox.last_error or "")



@pytest.mark.asyncio
async def test_api_create_webhook_with_preset_and_token(client, db, admin_token):
    payload = {
        "name": "My Homelab ntfy",
        "url": "https://ntfy.sh/my-test-topic",
        "service_type": "ntfy",
        "token": "super-secret-ntfy-token",
        "events": ["device.offline", "new_device"],
    }
    resp = await client.post(
        "/api/webhooks",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My Homelab ntfy"
    assert data["service_type"] == "ntfy"
    assert data["has_token"] is True
    assert "token" not in data  # Token value must never be leaked

    # Verify database record
    sub = (await db.execute(select(WebhookSubscription).where(WebhookSubscription.id == data["id"]))).scalar_one()
    assert sub.encrypted_token is not None
    assert sub.encrypted_token != "super-secret-ntfy-token"
    assert vault.decrypt(sub.encrypted_token) == "super-secret-ntfy-token"


@pytest.mark.asyncio
async def test_api_list_outbox_and_retry(client, db, admin_token):
    outbox = NotificationOutbox(
        event_type="device.offline",
        target_url="https://gotify.example.com/message",
        service_type="gotify",
        payload=json.dumps({"ip": "10.0.0.99"}),
        attempts=3,
        max_attempts=3,
        status="failed",
        last_error="HTTP 500: Internal Server Error",
        next_attempt_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(outbox)
    await db.commit()

    # GET /api/webhooks/outbox
    resp = await client.get("/api/webhooks/outbox", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    items = resp.json()
    assert any(item["id"] == outbox.id and item["status"] == "failed" for item in items)

    # POST /api/webhooks/outbox/{id}/retry
    orig_post = httpx.AsyncClient.post
    async def mock_post(self, url, *args, **kwargs):
        if str(url).startswith("/api/"):
            return await orig_post(self, url, *args, **kwargs)
        return httpx.Response(200, text="OK")

    with patch.object(httpx.AsyncClient, "post", mock_post):
        resp_retry = await client.post(
            f"/api/webhooks/outbox/{outbox.id}/retry",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp_retry.status_code == 200

    await db.refresh(outbox)
    assert outbox.status == "delivered"
    assert outbox.attempts == 1
