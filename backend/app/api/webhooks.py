"""Webhooks routing endpoints for GravityLAN."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.api.auth import get_current_admin
from app.models.webhook import WebhookSubscription
from app.schemas.webhook import WebhookSubscriptionCreate, WebhookSubscriptionResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

@router.get("", response_model=list[WebhookSubscriptionResponse])
async def list_webhooks(
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """List all registered webhook subscriptions."""
    result = await db.execute(select(WebhookSubscription).order_by(WebhookSubscription.created_at.desc()))
    return result.scalars().all()

@router.post("", response_model=WebhookSubscriptionResponse)
async def create_webhook(
    payload: WebhookSubscriptionCreate,
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Register a new webhook subscription."""
    events_str = ",".join(payload.events)
    
    new_sub = WebhookSubscription(
        url=payload.url,
        events=events_str,
        is_active=True
    )
    db.add(new_sub)
    await db.commit()
    await db.refresh(new_sub)
    return new_sub

@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Delete / revoke a webhook subscription."""
    result = await db.execute(select(WebhookSubscription).where(WebhookSubscription.id == webhook_id))
    db_sub = result.scalar_one_or_none()
    if not db_sub:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
        
    await db.delete(db_sub)
    await db.commit()
    return {"status": "ok", "message": "Webhook subscription deleted successfully"}
