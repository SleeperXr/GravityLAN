"""Write and prune the audit log (AuditEvent).

``record`` never raises and writes in its own session, so a failed action is logged even when
the request's own transaction rolls back, and a broken audit write never breaks the action.
Callers pass labels and short reasons only: no passwords, keys, tokens or terminal input.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from starlette.requests import HTTPConnection

from app.database import async_session
from app.models.audit import AuditEvent

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90
RESULTS = ("ok", "failed", "denied")
_ACTOR_STATE = "audit_actor"


def actor_from_identity(identity: str | None) -> str:
    """The caller as the audit log names it; a master token's value is never kept."""
    if not identity:
        return "anonymous"
    if identity.startswith("session_"):
        return "session"
    if identity.startswith("api_token:"):
        return identity[:120]
    if identity == "setup_mode":
        return "setup"
    return "master"


def remember_actor(conn: HTTPConnection, identity: str) -> None:
    """Called by the auth dependency: later audit records of this request know the caller."""
    state = getattr(conn, "state", None)
    if state is not None:
        setattr(state, _ACTOR_STATE, actor_from_identity(identity))


def actor_of(conn: HTTPConnection | None) -> str:
    if conn is None:
        return "system"
    actor = getattr(conn.state, _ACTOR_STATE, None)
    if actor:
        return actor
    # WebSockets authenticate outside the HTTP dependency; a session cookie is the only caller there
    return "session" if (conn.cookies.get("gravitylan_token") or "").startswith("session_") else "anonymous"


def source_ip(conn: HTTPConnection | None) -> str:
    return conn.client.host if conn is not None and conn.client else ""


def device_label(device) -> str:
    """'name (ip)' of a device, the way the audit list shows its target."""
    name = getattr(device, "display_name", None) or getattr(device, "hostname", None) or ""
    ip = getattr(device, "ip", "") or ""
    return f"{name} ({ip})" if name and name != ip else ip


async def record(
    conn: HTTPConnection | None,
    action: str,
    result: str = "ok",
    *,
    device_id: int | None = None,
    target: str = "",
    detail: str = "",
    actor: str | None = None,
) -> None:
    """Append one entry. Never raises."""
    try:
        event = AuditEvent(
            actor=(actor or actor_of(conn))[:120],
            source_ip=source_ip(conn)[:64],
            action=action[:60],
            result=result if result in RESULTS else "failed",
            device_id=device_id,
            target=(target or "")[:255],
            detail=(detail or "")[:500],
        )
        async with async_session() as db:
            db.add(event)
            await db.commit()
    except Exception as e:  # the action must not fail because its audit entry did
        logger.error("Audit: could not record %s (%s): %s", action, result, e)


async def prune(db, days: int = RETENTION_DAYS) -> int:
    """Delete entries older than ``days``; returns how many."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    res = await db.execute(delete(AuditEvent).where(AuditEvent.created_at < cutoff))
    await db.commit()
    return res.rowcount or 0
