"""Webhooks routing endpoints for GravityLAN."""

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_bearer_admin, get_current_admin
from app.database import get_db
from app.models.webhook import NotificationOutbox, WebhookSubscription
from app.schemas.webhook import (
    NotificationOutboxResponse,
    WebhookSubscriptionCreate,
    WebhookSubscriptionResponse,
)
from app.services.audit import record as audit
from app.services.secret_vault import vault
from app.services.stepup import require_step_up

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.get("", response_model=list[WebhookSubscriptionResponse])
async def list_webhooks(
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all registered webhook subscriptions."""
    result = await db.execute(select(WebhookSubscription).order_by(WebhookSubscription.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=WebhookSubscriptionResponse, dependencies=[Depends(require_step_up("credentials"))])
async def create_webhook(
    payload: WebhookSubscriptionCreate,
    request: Request,
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Register a new webhook or notification service subscription."""
    events_str = ",".join(payload.events)
    enc_token = vault.encrypt_optional(payload.token.strip()) if payload.token and payload.token.strip() else None

    new_sub = WebhookSubscription(
        name=payload.name.strip() if payload.name else None,
        url=payload.url,
        service_type=payload.service_type,
        encrypted_token=enc_token,
        events=events_str,
        is_active=True,
    )
    db.add(new_sub)
    await db.commit()
    await db.refresh(new_sub)
    await audit(request, "webhook.create", target=urlparse(new_sub.url).hostname or "", detail=events_str)
    return new_sub


@router.delete("/{webhook_id}", dependencies=[Depends(require_step_up("credentials"))])
async def delete_webhook(
    webhook_id: int,
    request: Request,
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete / revoke a webhook subscription."""
    result = await db.execute(select(WebhookSubscription).where(WebhookSubscription.id == webhook_id))
    db_sub = result.scalar_one_or_none()
    if not db_sub:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")

    await db.delete(db_sub)
    await db.commit()
    await audit(request, "webhook.delete", target=urlparse(db_sub.url).hostname or "")
    return {"status": "ok", "message": "Webhook subscription deleted successfully"}


@router.get("/outbox", response_model=list[NotificationOutboxResponse])
async def list_outbox_notifications(
    limit: int = 50,
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List recent notification outbox delivery entries (newest first)."""
    result = await db.execute(
        select(NotificationOutbox).order_by(NotificationOutbox.created_at.desc()).limit(min(limit, 200))
    )
    return result.scalars().all()


@router.post("/outbox/{outbox_id}/retry", dependencies=[Depends(require_step_up("credentials"))])
async def retry_outbox_notification(
    outbox_id: int,
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reset delivery status and attempts on an outbox entry and trigger immediate delivery."""
    from datetime import datetime, timezone
    from app.services.webhook_service import deliver_pending_outbox

    result = await db.execute(select(NotificationOutbox).where(NotificationOutbox.id == outbox_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Outbox entry not found")

    entry.status = "pending"
    entry.attempts = 0
    entry.next_attempt_at = datetime.now(timezone.utc).replace(tzinfo=None)
    entry.last_error = None
    await db.commit()

    await deliver_pending_outbox(db)
    return {"status": "ok", "message": f"Outbox entry {outbox_id} reset for retry"}


@router.post("/test")
async def test_webhook_dispatch(
    event: str = Body("test.event", embed=True),
    data: dict = Body({"status": "testing"}, embed=True),
    token: str = Depends(get_current_admin),
):
    """Trigger a mock/test webhook event to verify integrations."""
    from app.services.webhook_service import trigger_webhooks

    await trigger_webhooks(event_type=event, data=data)
    return {"status": "ok", "message": f"Webhook test event '{event}' scheduled for dispatch."}


@router.get("/test")
async def test_webhook_dispatch_get(
    event: str = "test.event",
    token: str = Depends(get_bearer_admin),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a mock/test webhook event via GET query parameter. Raises 404 if no webhooks exist.

    Needs an API token in the 'Authorization: Bearer' header; a session cookie alone is
    rejected (403), so a link on another site cannot fire webhooks. Browser sessions use
    POST /api/webhooks/test.
    """
    result = await db.execute(select(WebhookSubscription).where(WebhookSubscription.is_active == True))
    active_subs = result.scalars().all()
    if not active_subs:
        raise HTTPException(status_code=404, detail="No active webhooks configured")

    from datetime import datetime, timezone
    from app.services.webhook_service import trigger_webhooks

    mock_data = {
        "status": "testing",
        "triggered_by": "GET /api/webhooks/test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await trigger_webhooks(event_type=event, data=mock_data)
    return {"status": "ok", "message": f"Webhook test event '{event}' scheduled for dispatch via GET."}
