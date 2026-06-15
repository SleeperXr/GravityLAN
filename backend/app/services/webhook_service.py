"""Webhook Dispatcher Service for GravityLAN events."""

import asyncio
import logging
import httpx
from datetime import datetime, timezone
from sqlalchemy import select
from app.database import async_session
from app.models.webhook import WebhookSubscription

logger = logging.getLogger(__name__)

async def trigger_webhooks(event_type: str, data: dict):
    """Trigger registered webhooks for a specific event type in the background."""
    asyncio.create_task(_dispatch_webhooks(event_type, data))

async def _dispatch_webhooks(event_type: str, data: dict):
    """Asynchronously dispatches webhook events to all registered subscribers."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(WebhookSubscription).where(WebhookSubscription.is_active == True)
            )
            subscriptions = result.scalars().all()
    except Exception as e:
        logger.error(f"Webhook: Failed to query subscriptions from database: {e}")
        return

    # Filter subscriptions that match the event_type
    target_subs = []
    for sub in subscriptions:
        sub_events = [e.strip() for e in sub.events.split(",") if e.strip()]
        if event_type in sub_events:
            target_subs.append(sub)

    if not target_subs:
        return

    payload = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data
    }

    async with httpx.AsyncClient(timeout=5.0) as client:
        tasks = []
        for sub in target_subs:
            tasks.append(_send_webhook_post(client, sub.url, payload))
        await asyncio.gather(*tasks, return_exceptions=True)

async def _send_webhook_post(client: httpx.AsyncClient, url: str, payload: dict):
    """Sends a single POST request to the target webhook URL."""
    try:
        response = await client.post(url, json=payload)
        if response.status_code >= 400:
            logger.warning(
                f"Webhook: Target URL '{url}' returned status code {response.status_code}"
            )
        else:
            logger.debug(f"Webhook: Successfully dispatched event to '{url}'")
    except httpx.HTTPError as e:
        logger.error(f"Webhook: Failed to post to '{url}': {e}")
    except Exception as e:
        logger.error(f"Webhook: Unexpected error posting to '{url}': {e}")
