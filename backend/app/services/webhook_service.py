"""Webhook and Notification Dispatcher Service with Outbox and Retries for GravityLAN."""

import asyncio
import ipaddress
import json
import logging
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from app.database import async_session
from app.models.webhook import NotificationOutbox, WebhookSubscription
from app.schemas.webhook import check_webhook_url, is_blocked_webhook_ip
from app.services.secret_vault import vault

logger = logging.getLogger(__name__)

def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

_background_webhook_tasks: set[asyncio.Task] = set()

EVENT_ALIASES = {
    "new_device": {"new_device", "device.new"},
    "device.new": {"new_device", "device.new"},
    "ip_changed": {"ip_changed", "device.ip_changed"},
    "device.ip_changed": {"ip_changed", "device.ip_changed"},
    "device.offline": {"device.offline", "offline"},
    "device.online": {"device.online", "online"},
}


def format_event_notification(event_type: str, data: dict) -> tuple[str, str, int, list[str]]:
    """Return (title, message, priority_1_to_10, tags) for an event notification."""
    alias_key = event_type
    for canonical, aliases in EVENT_ALIASES.items():
        if event_type in aliases:
            alias_key = canonical
            break

    if alias_key in ("device.offline", "offline"):
        dev_name = data.get("display_name") or data.get("hostname") or data.get("ip") or "Device"
        ip = data.get("ip", "unknown")
        return (
            "GravityLAN: Device Offline",
            f"Device '{dev_name}' ({ip}) is offline",
            8,
            ["warning", "skull"],
        )

    if alias_key in ("device.online", "online"):
        dev_name = data.get("display_name") or data.get("hostname") or data.get("ip") or "Device"
        ip = data.get("ip", "unknown")
        return (
            "GravityLAN: Device Online",
            f"Device '{dev_name}' ({ip}) is back online",
            5,
            ["white_check_mark"],
        )

    if alias_key in ("new_device", "device.new"):
        dev_name = data.get("hostname") or data.get("vendor") or data.get("ip") or "New device"
        ip = data.get("ip", "unknown")
        mac = data.get("mac") or "N/A"
        return (
            "GravityLAN: New Device Discovered",
            f"New device discovered: {dev_name} (IP: {ip}, MAC: {mac})",
            5,
            ["sparkles", "computer"],
        )

    if alias_key in ("device.ip_changed", "ip_changed"):
        dev_name = data.get("display_name") or data.get("hostname") or "Device"
        old_ip = data.get("old_ip", "unknown")
        new_ip = data.get("new_ip", "unknown")
        return (
            "GravityLAN: IP Address Changed",
            f"Device '{dev_name}' changed IP from {old_ip} to {new_ip}",
            5,
            ["satellite"],
        )

    if alias_key == "scan.complete":
        hosts_found = data.get("hosts_found", 0)
        return (
            "GravityLAN: Scan Complete",
            f"Network discovery scan complete: {hosts_found} hosts found",
            3,
            ["mag"],
        )

    return (
        f"GravityLAN: {event_type}",
        json.dumps(data, ensure_ascii=False),
        5,
        ["bell"],
    )


def prepare_request_for_service(
    service_type: str, url: str, token: str | None, event_type: str, data: dict
) -> tuple[str, dict[str, str], dict | bytes]:
    """Prepare target URL, headers, and payload body (json dict or raw bytes) based on service preset."""
    title, message, prio, tags = format_event_notification(event_type, data)

    if service_type == "ntfy":
        ntfy_prio = "high" if prio >= 8 else ("low" if prio <= 3 else "default")
        headers = {
            "Title": title,
            "Priority": ntfy_prio,
            "Tags": ",".join(tags),
            "Content-Type": "text/plain; charset=utf-8",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return url, headers, message.encode("utf-8")

    if service_type == "gotify":
        parsed = urlparse(url)
        eff_url = url
        if not parsed.path.endswith("/message"):
            eff_url = url.rstrip("/") + "/message"
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Gotify-Key"] = token
        body = {"title": title, "message": message, "priority": prio}
        return eff_url, headers, body

    # Default: generic webhook
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    return url, headers, body


async def _blocked_target_reason(url: str) -> str | None:
    """Why ``url`` must not be posted to, or None when it may."""
    try:
        check_webhook_url(url)
    except ValueError as e:
        return str(e)

    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return None  # httpx reports resolution failure
    for *_, sockaddr in infos:
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if is_blocked_webhook_ip(addr):
            return f"{parsed.hostname} resolves to {addr}, a loopback, link-local or metadata address"
    return None


async def trigger_webhooks(event_type: str, data: dict):
    """Enqueue registered webhooks and notification presets into the persistent outbox and trigger dispatch."""
    task = asyncio.create_task(_enqueue_and_dispatch(event_type, data))
    _background_webhook_tasks.add(task)
    task.add_done_callback(_background_webhook_tasks.discard)


async def _enqueue_and_dispatch(event_type: str, data: dict):
    """Enqueues events into NotificationOutbox and immediately delivers pending entries."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(WebhookSubscription).where(WebhookSubscription.is_active == True)
            )
            subscriptions = result.scalars().all()

            match_events = EVENT_ALIASES.get(event_type, {event_type})
            target_subs = []
            for sub in subscriptions:
                sub_events = [e.strip() for e in sub.events.split(",") if e.strip()]
                if any(e in match_events for e in sub_events):
                    target_subs.append(sub)

            if not target_subs:
                return

            now = _utc_now()
            for sub in target_subs:
                entry = NotificationOutbox(
                    subscription_id=sub.id,
                    event_type=event_type,
                    target_url=sub.url,
                    service_type=sub.service_type or "webhook",
                    encrypted_token=sub.encrypted_token,
                    payload=json.dumps(data),
                    attempts=0,
                    max_attempts=3,
                    status="pending",
                    next_attempt_at=now,
                    created_at=now,
                )
                db.add(entry)
            await db.commit()

            await deliver_pending_outbox(db)
    except Exception as e:
        logger.error(f"Webhook: Failed to enqueue outbox notifications for {event_type}: {e}", exc_info=True)


# Backwards compatibility alias for tests and external callers
_dispatch_webhooks = _enqueue_and_dispatch


async def _send_webhook_post(client: httpx.AsyncClient, url: str, payload: dict):
    """Sends a single POST request to the target webhook URL (compat helper)."""
    reason = await _blocked_target_reason(url)
    if reason:
        logger.warning("Webhook: refusing to post to '%s': %s", url, reason)
        return
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


async def deliver_pending_outbox(db=None) -> int:
    """Deliver any pending outbox notifications whose next_attempt_at has arrived.

    Returns the count of successfully delivered entries.
    """
    if db is None:
        async with async_session() as session:
            return await deliver_pending_outbox(session)

    now = _utc_now()
    query = (
        select(NotificationOutbox)
        .where(
            NotificationOutbox.status == "pending",
            NotificationOutbox.next_attempt_at <= now,
            NotificationOutbox.attempts < NotificationOutbox.max_attempts,
        )
        .order_by(NotificationOutbox.created_at.asc())
        .limit(50)
    )
    result = await db.execute(query)
    entries = result.scalars().all()
    if not entries:
        return 0

    delivered_count = 0
    async with httpx.AsyncClient(timeout=5.0) as client:
        for entry in entries:
            # Check target safety
            reason = await _blocked_target_reason(entry.target_url)
            if reason:
                logger.warning("Notification Outbox: Refusing to post to '%s': %s", entry.target_url, reason)
                entry.attempts += 1
                entry.last_error = f"Blocked target: {reason}"
                entry.status = "failed"
                continue

            # Decrypt token if present
            raw_token = None
            if entry.encrypted_token:
                try:
                    raw_token = vault.decrypt_optional(entry.encrypted_token)
                except Exception as exc:
                    logger.error("Notification Outbox: Failed to decrypt secret token: %s", exc)

            payload_data = {}
            if entry.payload:
                try:
                    payload_data = json.loads(entry.payload)
                except Exception:
                    payload_data = {"raw": entry.payload}

            eff_url, headers, body = prepare_request_for_service(
                entry.service_type, entry.target_url, raw_token, entry.event_type, payload_data
            )

            try:
                if isinstance(body, bytes):
                    resp = await client.post(eff_url, content=body, headers=headers)
                else:
                    resp = await client.post(eff_url, json=body, headers=headers)

                if resp.status_code < 400:
                    entry.status = "delivered"
                    entry.delivered_at = datetime.now(timezone.utc)
                    entry.attempts += 1
                    entry.last_error = None
                    delivered_count += 1
                    logger.debug("Notification Outbox: Successfully delivered event %s to %s", entry.event_type, eff_url)
                else:
                    entry.attempts += 1
                    err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    entry.last_error = err_msg
                    logger.warning("Notification Outbox: %s returned %d (attempt %d/%d)", eff_url, resp.status_code, entry.attempts, entry.max_attempts)
                    if entry.attempts >= entry.max_attempts:
                        entry.status = "failed"
                    else:
                        backoff = 10 * (2 ** (entry.attempts - 1))
                        entry.next_attempt_at = _utc_now() + timedelta(seconds=backoff)
            except Exception as e:
                entry.attempts += 1
                entry.last_error = str(e)[:300]
                logger.error("Notification Outbox: Delivery error to %s: %s (attempt %d/%d)", eff_url, e, entry.attempts, entry.max_attempts)
                if entry.attempts >= entry.max_attempts:
                    entry.status = "failed"
                else:
                    backoff = 10 * (2 ** (entry.attempts - 1))
                    entry.next_attempt_at = _utc_now() + timedelta(seconds=backoff)

        await db.commit()

    return delivered_count


async def process_outbox() -> int:
    """Wrapper for the background scheduler loop to process retries."""
    async with async_session() as db:
        return await deliver_pending_outbox(db)
