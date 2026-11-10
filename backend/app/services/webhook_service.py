"""Webhook and Notification Dispatcher Service with Outbox and Retries for GravityLAN."""

import asyncio
import ipaddress
import json
import logging
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

import httpx
from sqlalchemy import select

from app.database import async_session
from app.models.webhook import NotificationOutbox, WebhookSubscription
from app.schemas.webhook import check_webhook_url, is_blocked_webhook_ip
from app.services.secret_vault import VaultError, vault

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_background_webhook_tasks: set[asyncio.Task] = set()
# One delivery pass at a time: an event's own pass and the retry loop must not send the same entry twice
_delivery_lock = asyncio.Lock()
_shared_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    """Returns a shared httpx.AsyncClient instance, avoiding high per-request startup/teardown costs."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(timeout=5.0)
    return _shared_client


async def drain_webhook_tasks(timeout: float = 5.0) -> int:
    """Let running enqueue/delivery tasks finish (also those they start meanwhile) for up to ``timeout``.

    Returns how many were still running at the deadline. Those are cancelled: an event they had
    already written to the outbox is sent by the retry loop after the next start.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while _background_webhook_tasks:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        await asyncio.wait(set(_background_webhook_tasks), timeout=remaining)
    left = list(_background_webhook_tasks)
    for task in left:
        task.cancel()
    if left:
        await asyncio.gather(*left, return_exceptions=True)
        logger.warning("Webhook: %d deliveries still running at shutdown were cancelled", len(left))
    return len(left)


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


Notification = tuple[str, str, int, list[str]]


def _device_label(data: dict, *fields: str, fallback: str) -> str:
    return next((data[f] for f in fields if data.get(f)), fallback)


def _offline_text(data: dict) -> Notification:
    name = _device_label(data, "display_name", "hostname", "ip", fallback="Device")
    return "GravityLAN: Device Offline", f"Device '{name}' ({data.get('ip', 'unknown')}) is offline", 8, ["warning", "skull"]


def _online_text(data: dict) -> Notification:
    name = _device_label(data, "display_name", "hostname", "ip", fallback="Device")
    return "GravityLAN: Device Online", f"Device '{name}' ({data.get('ip', 'unknown')}) is back online", 5, ["white_check_mark"]


def _new_device_text(data: dict) -> Notification:
    name = _device_label(data, "hostname", "vendor", "ip", fallback="New device")
    message = f"New device discovered: {name} (IP: {data.get('ip', 'unknown')}, MAC: {data.get('mac') or 'N/A'})"
    return "GravityLAN: New Device Discovered", message, 5, ["sparkles", "computer"]


def _ip_changed_text(data: dict) -> Notification:
    name = _device_label(data, "display_name", "hostname", fallback="Device")
    message = f"Device '{name}' changed IP from {data.get('old_ip', 'unknown')} to {data.get('new_ip', 'unknown')}"
    return "GravityLAN: IP Address Changed", message, 5, ["satellite"]


def _scan_complete_text(data: dict) -> Notification:
    return "GravityLAN: Scan Complete", f"Network discovery scan complete: {data.get('hosts_found', 0)} hosts found", 3, ["mag"]


def _test_text(data: dict) -> Notification:
    dest = data.get("destination") or "endpoint"
    return "GravityLAN: Test Notification", f"Test notification for {dest} delivered successfully.", 5, ["white_check_mark", "bell"]


# Event (canonical name or its short form) -> text of the notification
_EVENT_TEXTS = {
    "device.offline": _offline_text, "offline": _offline_text,
    "device.online": _online_text, "online": _online_text,
    "new_device": _new_device_text, "device.new": _new_device_text,
    "device.ip_changed": _ip_changed_text, "ip_changed": _ip_changed_text,
    "scan.complete": _scan_complete_text,
    "test.event": _test_text,
}


def _canonical_event(event_type: str) -> str:
    return next((canonical for canonical, aliases in EVENT_ALIASES.items() if event_type in aliases), event_type)


def format_event_notification(event_type: str, data: dict) -> Notification:
    """Return (title, message, priority_1_to_10, tags) for an event notification."""
    text = _EVENT_TEXTS.get(_canonical_event(event_type))
    if text:
        return text(data)
    return f"GravityLAN: {event_type}", json.dumps(data, ensure_ascii=False), 5, ["bell"]


def _ntfy_request(url: str, token: str | None, note: Notification) -> tuple[str, dict[str, str], bytes]:
    title, message, prio, tags = note
    headers = {
        "Title": title,
        "Priority": "high" if prio >= 8 else ("low" if prio <= 3 else "default"),
        "Tags": ",".join(tags),
        "Content-Type": "text/plain; charset=utf-8",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return url, headers, message.encode("utf-8")


def _gotify_request(url: str, token: str | None, note: Notification) -> tuple[str, dict[str, str], dict]:
    title, message, prio, _tags = note
    parsed = urlparse(url)
    if not parsed.path.rstrip("/").endswith("/message"):
        url = urlunparse(parsed._replace(path=parsed.path.rstrip("/") + "/message"))
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Gotify-Key"] = token
    return url, headers, {"title": title, "message": message, "priority": prio}


def prepare_request_for_service(
    service_type: str, url: str, token: str | None, event_type: str, data: dict
) -> tuple[str, dict[str, str], dict | bytes]:
    """Prepare target URL, headers, and payload body (json dict or raw bytes) based on service preset."""
    note = format_event_notification(event_type, data)
    if service_type == "ntfy":
        return _ntfy_request(url, token, note)
    if service_type == "gotify":
        return _gotify_request(url, token, note)

    # Default: generic webhook
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return url, headers, {"event": event_type, "timestamp": datetime.now(timezone.utc).isoformat(), "data": data}


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


def _decrypt_token(sub: WebhookSubscription) -> str | None:
    """Decrypt the subscription token using vault, returning None on missing or invalid token."""
    if not sub.encrypted_token:
        return None
    try:
        return vault.decrypt_optional(sub.encrypted_token)
    except (VaultError, ValueError, TypeError) as exc:
        logger.error("Notification Outbox: Failed to decrypt secret token: %s", exc)
        return None


def _parse_payload(payload_raw: str | None) -> dict:
    """Parse outbox entry JSON payload into a dictionary, falling back to raw payload."""
    if not payload_raw:
        return {}
    try:
        parsed = json.loads(payload_raw)
        return parsed if isinstance(parsed, dict) else {"raw": payload_raw}
    except (json.JSONDecodeError, TypeError):
        return {"raw": payload_raw}


def _record_success(entry: NotificationOutbox) -> None:
    """Mark an outbox entry as successfully delivered."""
    entry.status = "delivered"
    entry.delivered_at = _utc_now()
    entry.attempts += 1
    entry.last_error = None


def _record_failure(entry: NotificationOutbox, error_msg: str) -> None:
    """Record an attempt failure, scheduling exponential backoff or marking as failed."""
    entry.attempts += 1
    entry.last_error = error_msg[:300]
    if entry.attempts >= entry.max_attempts:
        entry.status = "failed"
    else:
        backoff = 10 * (2 ** (entry.attempts - 1))
        entry.next_attempt_at = _utc_now() + timedelta(seconds=backoff)


async def _execute_and_record_delivery(
    client: httpx.AsyncClient,
    eff_url: str,
    headers: dict[str, str],
    body: dict | bytes,
    entry: NotificationOutbox,
) -> bool:
    """Perform HTTP post and record success or backoff failure on the entry."""
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
            _record_success(entry)
            logger.debug("Notification Outbox: Successfully delivered event %s to %s", entry.event_type, eff_url)
            return True

        text = getattr(resp, "text", "")[:200]
        logger.warning(
            "Notification Outbox: %s returned %d (attempt %d/%d)",
            eff_url, status_code, entry.attempts + 1, entry.max_attempts,
        )
        _record_failure(entry, f"HTTP {status_code}: {text}")
        return False
    except httpx.HTTPError as e:
        logger.error(
            "Notification Outbox: Delivery error to %s: %s (attempt %d/%d)",
            eff_url, e, entry.attempts + 1, entry.max_attempts,
        )
        _record_failure(entry, str(e))
        return False
    except OSError as e:
        logger.error(
            "Notification Outbox: Network error to %s: %s (attempt %d/%d)",
            eff_url, e, entry.attempts + 1, entry.max_attempts,
        )
        _record_failure(entry, str(e))
        return False


async def _deliver_single_entry(
    client: httpx.AsyncClient,
    entry: NotificationOutbox,
    sub: WebhookSubscription | None,
) -> bool:
    """Deliver a single outbox entry, updating its status, attempts, error, and next attempt time.

    The token stays on the subscription, so a deleted or disabled subscription sends nothing more.
    Returns True if successfully delivered, False otherwise.
    """
    if sub is None or not sub.is_active:
        entry.status = "failed"
        entry.last_error = "Subscription removed"
        return False

    raw_token = _decrypt_token(sub)
    payload_data = _parse_payload(entry.payload)

    eff_url, headers, body = prepare_request_for_service(
        entry.service_type, entry.target_url, raw_token, entry.event_type, payload_data
    )

    return await _execute_and_record_delivery(client, eff_url, headers, body, entry)


async def trigger_webhooks(event_type: str, data: dict):
    """Enqueue registered webhooks and notification presets into the persistent outbox and trigger dispatch."""
    task = asyncio.create_task(_enqueue_and_dispatch(event_type, data))
    _background_webhook_tasks.add(task)
    task.add_done_callback(_background_webhook_tasks.discard)
    return task


_PENDING_EVENTS_KEY = "gravitylan_pending_webhooks"


def _fire_pending_events(session) -> None:
    # after_commit is synchronous: hand each event to trigger_webhooks on the running loop
    for event_type, data in session.info.pop(_PENDING_EVENTS_KEY, []):
        task = asyncio.get_running_loop().create_task(trigger_webhooks(event_type=event_type, data=data))
        _background_webhook_tasks.add(task)
        task.add_done_callback(_background_webhook_tasks.discard)


def _drop_pending_events(session, _previous_transaction=None) -> None:
    session.info.pop(_PENDING_EVENTS_KEY, None)


def trigger_webhooks_after_commit(db, event_type: str, data: dict) -> None:
    """Send an event only once ``db`` commits the change it reports, and never if it rolls back.

    For events about state the caller is still writing (a device going offline): sent before the
    commit, a failed or retried transaction would report a change that never happened, or report it twice.
    """
    from sqlalchemy import event as sa_event

    sync_session = db.sync_session
    # Tie the event to a transaction: without one, rollback() is a no-op that fires no event,
    # and the next commit would send what the caller meant to discard
    if not sync_session.in_transaction():
        sync_session.begin()
    sync_session.info.setdefault(_PENDING_EVENTS_KEY, []).append((event_type, data))
    if not sa_event.contains(sync_session, "after_commit", _fire_pending_events):
        sa_event.listen(sync_session, "after_commit", _fire_pending_events)
        # after_soft_rollback fires on every rollback(), after_rollback only when a transaction was open
        sa_event.listen(sync_session, "after_soft_rollback", _drop_pending_events)


def _filter_by_event_type(
    subscriptions: list[WebhookSubscription],
    event_type: str,
) -> list[WebhookSubscription]:
    """Return subscriptions that match the event type or any of its aliases."""
    match_events = EVENT_ALIASES.get(event_type, {event_type})
    matching: list[WebhookSubscription] = []
    for sub in subscriptions:
        sub_events = [e.strip() for e in sub.events.split(",") if e.strip()]
        if any(e in match_events for e in sub_events):
            matching.append(sub)
    return matching


def _match_subscriptions(
    subscriptions: list[WebhookSubscription],
    event_type: str,
    data: dict,
) -> list[WebhookSubscription]:
    """Select subscriptions relevant for the given event and payload."""
    target_sub_id = data.get("subscription_id") if isinstance(data, dict) else None
    if event_type == "test.event" and target_sub_id is not None:
        return [sub for sub in subscriptions if sub.id == target_sub_id]

    target_subs = _filter_by_event_type(subscriptions, event_type)
    if not target_subs and event_type == "test.event":
        return list(subscriptions)
    return target_subs


def _build_outbox_entries(
    target_subs: list[WebhookSubscription],
    event_type: str,
    data: dict,
    now: datetime,
) -> list[NotificationOutbox]:
    """Create pending NotificationOutbox records for target subscriptions."""
    payload_str = json.dumps(data)
    return [
        NotificationOutbox(
            subscription_id=sub.id,
            event_type=event_type,
            target_url=sub.url,
            service_type=sub.service_type or "webhook",
            payload=payload_str,
            attempts=0,
            max_attempts=3,
            status="pending",
            next_attempt_at=now,
            created_at=now,
        )
        for sub in target_subs
    ]


async def _enqueue_and_dispatch(event_type: str, data: dict):
    """Enqueues events into NotificationOutbox and immediately delivers entries."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(WebhookSubscription).where(WebhookSubscription.is_active == True)
            )
            subscriptions = list(result.scalars().all())
            target_subs = _match_subscriptions(subscriptions, event_type, data)
            if not target_subs:
                return

            now = _utc_now()
            entries = _build_outbox_entries(target_subs, event_type, data, now)
            db.add_all(entries)

            # Stored before the first attempt: after a crash or restart the retry loop picks them up
            await db.commit()
            await deliver_pending_outbox(db)
    except Exception as e:
        logger.exception("Webhook: Failed to enqueue outbox notifications for %s: %s", event_type, e)


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
            response = await client.post(url, content=payload, headers=headers)
        else:
            response = await client.post(url, json=payload, headers=headers)
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


async def _attempt_delivery(client: httpx.AsyncClient, entry: NotificationOutbox, sub: WebhookSubscription | None) -> bool:
    """Deliver one entry. Anything that goes wrong is a failed attempt, or the entry would stay
    pending at the head of the queue and stop every notification behind it."""
    try:
        return await _deliver_single_entry(client, entry, sub)
    except Exception as exc:
        logger.error("Notification Outbox: Delivery of entry %s failed: %s", entry.id, type(exc).__name__)
        _record_failure(entry, str(exc))
        return False


async def deliver_pending_outbox(db=None) -> int:
    """Deliver any pending outbox notifications whose next_attempt_at has arrived.

    Returns the count of successfully delivered entries.
    """
    if db is None:
        async with async_session() as session:
            return await deliver_pending_outbox(session)

    async with _delivery_lock:
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

        # Batch-fetch all subscriptions for these entries to prevent N+1 queries in the loop
        sub_ids = {e.subscription_id for e in entries if e.subscription_id}
        subs_by_id: dict[int, WebhookSubscription] = {}
        if sub_ids:
            sub_query = select(WebhookSubscription).where(WebhookSubscription.id.in_(sub_ids))
            sub_res = await db.execute(sub_query)
            subs_by_id = {s.id: s for s in sub_res.scalars().all()}

        delivered_count = 0
        client = await _get_client()
        for entry in entries:
            sub = subs_by_id.get(entry.subscription_id) if entry.subscription_id else None
            if await _attempt_delivery(client, entry, sub):
                delivered_count += 1
            # Per entry: a crash in this pass must not send the earlier ones again
            await db.commit()

        return delivered_count


async def process_outbox() -> int:
    """Wrapper for the background scheduler loop to process retries."""
    async with async_session() as db:
        return await deliver_pending_outbox(db)
