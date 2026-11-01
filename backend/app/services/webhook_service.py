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
_shared_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    """Returns a shared httpx.AsyncClient instance, avoiding high per-request startup/teardown costs."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(timeout=5.0)
    return _shared_client


async def close_webhook_client():
    """Close the shared client on application shutdown."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None

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


async def _deliver_single_entry(client: httpx.AsyncClient, entry: NotificationOutbox) -> bool:
    """Deliver a single outbox entry, updating its status, attempts, error, and next attempt time.

    Returns True if successfully delivered, False otherwise.
    """
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
        resp = await _send_webhook_post(client, eff_url, body, headers=headers)

        if resp is None:
            # Target blocked by SSRF protection
            entry.attempts += 1
            entry.status = "failed"
            entry.last_error = f"Blocked target: {eff_url}"
            logger.warning("Notification Outbox: Refused to post to blocked target '%s'", eff_url)
            return False

        status_code = getattr(resp, "status_code", 200)
        if not isinstance(status_code, int):
            status_code = 200

        if status_code < 400:
            entry.status = "delivered"
            entry.delivered_at = _utc_now()
            entry.attempts += 1
            entry.last_error = None
            logger.debug("Notification Outbox: Successfully delivered event %s to %s", entry.event_type, eff_url)
            return True

        entry.attempts += 1
        text = getattr(resp, "text", "")[:200]
        err_msg = f"HTTP {status_code}: {text}"
        entry.last_error = err_msg
        logger.warning(
            "Notification Outbox: %s returned %d (attempt %d/%d)",
            eff_url, status_code, entry.attempts, entry.max_attempts,
        )
        if entry.attempts >= entry.max_attempts:
            entry.status = "failed"
        else:
            backoff = 10 * (2 ** (entry.attempts - 1))
            entry.next_attempt_at = _utc_now() + timedelta(seconds=backoff)
        return False
    except Exception as e:
        entry.attempts += 1
        entry.last_error = str(e)[:300]
        logger.error(
            "Notification Outbox: Delivery error to %s: %s (attempt %d/%d)",
            eff_url, e, entry.attempts, entry.max_attempts,
        )
        if entry.attempts >= entry.max_attempts:
            entry.status = "failed"
        else:
            backoff = 10 * (2 ** (entry.attempts - 1))
            entry.next_attempt_at = _utc_now() + timedelta(seconds=backoff)
        return False


async def trigger_webhooks(event_type: str, data: dict):
    """Enqueue registered webhooks and notification presets into the persistent outbox and trigger dispatch."""
    task = asyncio.create_task(_enqueue_and_dispatch(event_type, data))
    _background_webhook_tasks.add(task)
    task.add_done_callback(_background_webhook_tasks.discard)
    return task


async def _enqueue_and_dispatch(event_type: str, data: dict):
    """Enqueues events into NotificationOutbox and immediately delivers entries."""
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
            entries = []
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
                entries.append(entry)

            client = await _get_client()
            for entry in entries:
                await _deliver_single_entry(client, entry)

            await db.commit()
    except Exception as e:
        logger.error(f"Webhook: Failed to enqueue outbox notifications for {event_type}: {e}", exc_info=True)


# Backwards compatibility alias for tests and external callers
_dispatch_webhooks = _enqueue_and_dispatch


async def _send_webhook_post(
    client: httpx.AsyncClient,
    url: str,
    payload: dict | bytes,
    headers: dict[str, str] | None = None,
) -> httpx.Response | None:
    """Sends a single POST request to the target webhook URL."""
    reason = await _blocked_target_reason(url)
    if reason:
        logger.warning("Webhook: refusing to post to '%s': %s", url, reason)
        return None
    try:
        if isinstance(payload, bytes):
            if headers:
                response = await client.post(url, content=payload, headers=headers)
            else:
                response = await client.post(url, content=payload)
        else:
            if headers:
                response = await client.post(url, json=payload, headers=headers)
            else:
                response = await client.post(url, json=payload)
        if response.status_code >= 400:
            logger.warning(
                f"Webhook: Target URL '{url}' returned status code {response.status_code}"
            )
        else:
            logger.debug(f"Webhook: Successfully dispatched event to '{url}'")
        return response
    except httpx.HTTPError as e:
        logger.error(f"Webhook: Failed to post to '{url}': {e}")
        raise
    except Exception as e:
        logger.error(f"Webhook: Unexpected error posting to '{url}': {e}")
        raise


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
    client = await _get_client()
    for entry in entries:
        if await _deliver_single_entry(client, entry):
            delivered_count += 1

    await db.commit()

    return delivered_count


async def process_outbox() -> int:
    """Wrapper for the background scheduler loop to process retries."""
    async with async_session() as db:
        return await deliver_pending_outbox(db)
