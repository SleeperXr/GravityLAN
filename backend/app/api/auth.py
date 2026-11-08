import hashlib
import math
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Body, Response, Request, Header, WebSocket, Query
from fastapi.requests import HTTPConnection
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.services.audit import record as audit, remember_actor
from app.services import stepup
from app.services.stepup import require_step_up
from app.database import get_db
from app.models.setting import Setting
from app.config import settings
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

from app.services.auth_service import hash_password, verify_password, looks_hashed, secure_compare
from app.services.session_service import session_store
from app.services.agent_telemetry import _setting_cache

_READ_METHODS = ("GET", "HEAD")

# Paths that need one scope whatever the method (compared without a trailing slash)
_FIXED_SCOPES = {
    # GETs that start active scans: live discovery sweeps subnets and stores what it
    # finds, scan-ip runs nmap against an address (#43)
    "/api/scanner/live-discovery": "scanner:start",
    "/api/scanner/scan-ip": "scanner:start",
    # /test posts to every subscriber, so even its GET variant needs write access
    "/api/webhooks/test": "settings:write",
}
# Agent routes that hand out credentials or enroll a host: write access for every method
_AGENT_WRITE_PREFIXES = ("/api/agent/download/config", "/api/agent/token", "/api/agent/enroll")

# (path prefixes, scope for GET/HEAD, scope for other methods); the first match wins
_SCOPE_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("/api/devices", "/api/groups", "/api/services", "/api/interfaces"), "devices:read", "devices:write"),
    (("/api/topology",), "topology:read", "topology:write"),
    (("/api/network",), "network:read", "network:write"),
    (("/api/agent",), "agent:read", "agent:write"),  # also covers /api/agents
    (("/api/settings",), "settings:read", "settings:write"),
    (("/api/backup",), "backup:read", "backup:write"),
    (("/api/scanner",), "scanner:read", "scanner:start"),
    (("/api/webhooks",), "settings:read", "settings:write"),
    (("/api/summary", "/api/issues"), "devices:read", "devices:read"),  # general read permission
    (("/api/auth/tokens", "/api/logs", "/api/audit"), "settings:read", "settings:write"),
    (("/api/notifications", "/api/health"), "devices:read", "devices:write"),
)


def _required_scope_for(path: str, method: str) -> str | None:
    """Map an API path/method to the scope a read-only token needs."""
    fixed = _FIXED_SCOPES.get(path.rstrip("/"))
    if fixed:
        return fixed
    if path.startswith(_AGENT_WRITE_PREFIXES):
        return "agent:write"
    for prefixes, read_scope, write_scope in _SCOPE_RULES:
        if path.startswith(prefixes):
            return read_scope if method in _READ_METHODS else write_scope
    return None


_READONLY_FORBIDDEN_PATHS = ("/api/backup/export", "/api/settings/reset-db")
_READONLY_DEFAULT_SCOPES = {
    "devices:read", "topology:read", "network:read", "agent:read",
    "settings:read", "backup:read", "scanner:read"
}

# Routes the first-run wizard calls before any admin credential exists.
# Everything else stays closed until setup.complete is set (fresh install or
# after a factory reset), so an unconfigured instance cannot be exported,
# reconfigured or used to deploy agents by anyone on the LAN.
_SETUP_WIZARD_ROUTES = frozenset({
    ("GET", "/api/scanner/subnets"),
    ("GET", "/api/scanner/discovered"),
    ("POST", "/api/scanner/start"),
    ("POST", "/api/scanner/stop"),
    ("WEBSOCKET", "/api/scanner/ws"),
})


def _is_setup_wizard_route(conn: HTTPConnection) -> bool:
    """Return True when the request targets a route the setup wizard needs."""
    method = conn.scope.get("method") or conn.scope.get("type", "").upper()
    return (method, conn.url.path) in _SETUP_WIZARD_ROUTES


async def _verify_api_token(db: AsyncSession, token_val: str, conn: HTTPConnection) -> str:
    """Validate a read-only API token, enforce scopes, and update last_used_at."""
    h = hashlib.sha256(token_val.encode()).hexdigest()
    from app.models.api_token import ApiToken
    token_res = await db.execute(select(ApiToken).where(ApiToken.token_hash == h, ApiToken.is_active == True))
    db_token = token_res.scalar_one_or_none()

    if not db_token:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    _enforce_token_scopes(db_token, conn)
    await _touch_api_token(db, db_token)
    return f"api_token:{db_token.name}"


# Not scoped: who-am-I checks, and routes that do their own check (step-up, browser session)
_SCOPE_EXEMPT_PATHS = ("/api/auth/check", "/api/auth/me", "/api/ssh/sessions/prepare")
_SCOPE_EXEMPT_PREFIXES = ("/api/agent/enroll/", "/api/agent/deploy/", "/api/agent/uninstall/", "/api/agent/patches/")
# Token management, SSH and agent credentials/deployment are never open to an API token
_TOKEN_FORBIDDEN_PREFIXES = (
    "/api/auth/tokens", "/api/ssh", "/api/agent/download/config", "/api/agent/enroll", "/api/agent/adopt",
    "/api/agent/deploy", "/api/agent/uninstall", "/api/agent/patches",
)


def _token_scopes(db_token) -> set[str]:
    """The scopes of an API token; a token without any gets the read-only defaults."""
    if db_token.scopes:
        return {s.strip() for s in db_token.scopes.split(",") if s.strip()}
    return _READONLY_DEFAULT_SCOPES


def _is_scope_exempt(path: str) -> bool:
    return path in _SCOPE_EXEMPT_PATHS or path.startswith(_SCOPE_EXEMPT_PREFIXES)


def _is_forbidden_for_tokens(path: str) -> bool:
    return path in _READONLY_FORBIDDEN_PATHS or path.startswith(_TOKEN_FORBIDDEN_PREFIXES)


def _missing_scope_error(required_scope: str, method: str) -> HTTPException:
    detail = f"Token is missing the required scope '{required_scope}'."
    if method not in _READ_METHODS:
        detail = f"Read-only token cannot perform state-modifying actions. {detail}"
    return HTTPException(status_code=403, detail=detail)


def _enforce_token_scopes(db_token, conn: HTTPConnection) -> None:
    """Enforce scope rules for a read-only API token on HTTP requests."""
    if conn.scope.get("type") != "http":
        return

    method = conn.method
    path = conn.url.path
    if _is_scope_exempt(path):
        return

    if _is_forbidden_for_tokens(path):
        raise HTTPException(
            status_code=403,
            detail="Read-only token is not authorized for this administrative action. Token is not authorized for sensitive administrative actions."
        )

    required_scope = _required_scope_for(path, method)
    if required_scope and required_scope not in _token_scopes(db_token):
        raise _missing_scope_error(required_scope, method)


async def _authenticate_query_param(db: AsyncSession, token: str, conn: HTTPConnection) -> str:
    """Authenticate via query parameter (WebSockets ONLY)."""
    is_websocket = conn.scope.get("type") == "websocket"
    if not is_websocket:
        logger.warning("Security Warning: Attempted query parameter authentication on non-WebSocket route. Blocked.")
        raise HTTPException(
            status_code=401,
            detail="Query parameter authentication is restricted to WebSockets."
        )

    if token.startswith("session_"):
        session = session_store.get_session(token)
        if session:
            return token
    else:
        res_token = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
        master_setting = res_token.scalar_one_or_none()
        if master_setting and secure_compare(token, master_setting.value):
            return token
    raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_admin(
    conn: HTTPConnection,
    authorization: str | None = Header(None),
    token: str | None = Query(None),
    db: AsyncSession = Depends(get_db)
) -> str:
    """
    Dependency to validate authentication via Cookie, Authorization header, or Query param.
    Works for both HTTP Requests and WebSockets. Tells the audit log who the caller is
    ("session", "master", "api_token:<name>"; never a token's value).
    """
    identity = await _resolve_admin(conn, authorization, token, db)
    remember_actor(conn, identity)
    return identity


async def _setup_completed(db: AsyncSession) -> bool:
    row = (await db.execute(select(Setting).where(Setting.key == "setup.complete"))).scalar_one_or_none()
    return row is not None and row.value == "true"


def _warn_on_user_agent_change(session, headers, channel: str = "Session") -> None:
    """Weak plausibility check: a session used from another browser is logged, not refused."""
    req_ua = headers.get("user-agent")
    if session.user_agent and req_ua and session.user_agent != req_ua:
        logger.warning("%s User-Agent mismatch: expected '%s', got '%s'", channel, session.user_agent, req_ua)


async def _authenticate_cookie(db: AsyncSession, conn: HTTPConnection, cookie_token: str) -> str:
    """A browser session cookie, or the deprecated master token in the cookie."""
    if cookie_token.startswith("session_"):
        session = session_store.get_session(cookie_token)
        if not session:
            raise HTTPException(status_code=401, detail="Session expired or invalid")
        _warn_on_user_agent_change(session, conn.headers)
        return cookie_token

    master_token = await _load_master_token(db)
    if master_token and secure_compare(cookie_token, master_token):
        logger.warning(
            "DEPRECATION WARNING: Master-Token used in browser cookie. "
            "This legacy authentication path is deprecated and will be removed in a future release."
        )
        return cookie_token
    raise HTTPException(status_code=401, detail="Invalid token")


async def _resolve_admin(conn: HTTPConnection, authorization: str | None, token: str | None, db: AsyncSession) -> str:
    # 0. Before setup is complete no credentials exist: only the wizard's routes are open
    if not await _setup_completed(db):
        if _is_setup_wizard_route(conn):
            return "setup_mode"
        raise HTTPException(status_code=403, detail="Initial setup not completed.")

    # 1. Try Browser Cookie (Primary channel for Browser sessions)
    cookie_token = conn.cookies.get("gravitylan_token")
    if cookie_token:
        return await _authenticate_cookie(db, conn, cookie_token)

    # 2. Try Authorization Header (Primary channel for external API/Agent calls)
    if authorization and authorization.startswith("Bearer "):
        return await _authenticate_bearer(db, authorization, conn)

    # 3. Special Fallback Channel: Query Parameter (WebSockets ONLY)
    if token:
        return await _authenticate_query_param(db, token, conn)

    raise HTTPException(status_code=401, detail="Missing authentication token")


async def _authenticate_bearer(db: AsyncSession, authorization: str, conn: HTTPConnection) -> str:
    """Validate the token of an 'Authorization: Bearer' header (master or API token)."""
    token_val = authorization.removeprefix("Bearer ").strip()
    # Strictly reject Session IDs in the Authorization Header
    if token_val.startswith("session_"):
        logger.warning("Security Warning: Session ID submitted in Authorization Header. Rejected.")
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication method. Session IDs are only accepted via cookies."
        )

    # A. Check Master-Token
    res_token = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
    master_setting = res_token.scalar_one_or_none()
    if master_setting and secure_compare(token_val, master_setting.value):
        return token_val

    # B. Check Read-Only API Tokens
    return await _verify_api_token(db, token_val, conn)


async def get_bearer_admin(
    conn: HTTPConnection,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db)
) -> str:
    """
    Dependency for GET routes with side effects: only the Authorization header counts.

    SameSite=Lax still sends the session cookie when another site links or redirects
    the browser to a GET URL, so a cookie must not be enough to trigger an action there.
    Browser sessions use the POST variant of such routes instead.
    """
    if not (authorization and authorization.startswith("Bearer ")):
        raise HTTPException(
            status_code=403,
            detail=(
                "This GET endpoint only accepts an API token in the 'Authorization: Bearer' header. "
                "Browser sessions must use the POST variant."
            )
        )
    return await _authenticate_bearer(db, authorization, conn)

async def authenticate_websocket(
    websocket: WebSocket,
    endpoint_type: str,  # "logs" (Logs), "scanner" (Scan Status), "agent" (Agent metrics)
    device_id: int | None = None,
    db: AsyncSession | None = None
) -> dict:
    """
    Centralized, secure helper to authenticate WebSocket connections.
    Enforces strict endpoint classification and channel policies.
    
    Supports:
    1. Browser-based clients: Authenticates via 'gravitylan_token' cookie (Session ID).
    2. External scripts / CLI: Authenticates via 'token' query parameter (Master Token, ONLY on 'logs' endpoints).
    3. Specialized Agents: Authenticates via 'token' query parameter (Agent Token, ONLY on 'agent' endpoints).
    4. Setup Bypass: Allowed ONLY on 'scanner' endpoints during initial configuration.
    
    Returns:
        dict: A dictionary containing auth info:
            {
                "authenticated": bool,
                "auth_type": "session" | "master" | "agent" | "master_legacy" | "setup_bypass",
                "identity": str
            }
    """
    if db is None:
        from app.database import async_session
        async with async_session() as session_ctx:
            return await _authenticate_websocket_impl(websocket, endpoint_type, device_id, session_ctx)
    else:
        return await _authenticate_websocket_impl(websocket, endpoint_type, device_id, db)


async def authenticate_websocket_authorized(
    websocket: WebSocket,
    endpoint_type: str,
    allowed_levels: tuple[str, ...] = ("session", "master", "master_legacy", "api_token"),
    device_id: int | None = None,
) -> dict | None:
    """
    Authenticate a WebSocket and enforce an authorization level.

    Returns the auth info dict when the client is authenticated AND the
    auth type is allowed, otherwise closes the connection and returns None.
    """
    auth_info = await authenticate_websocket(websocket, endpoint_type=endpoint_type, device_id=device_id)
    if not auth_info.get("authenticated"):
        return None
    if auth_info.get("auth_type") not in allowed_levels:
        await websocket.close(code=4003, reason="Unauthorized access level")
        return None
    return auth_info

async def _touch_api_token(db: AsyncSession, db_token) -> None:
    """Throttled last_used_at update for an API token."""
    try:
        now = datetime.now(timezone.utc)
        last_used = db_token.last_used_at
        if last_used and last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=timezone.utc)
        if not last_used or (now - last_used).total_seconds() > 60:
            db_token.last_used_at = now
            await db.commit()
    except SQLAlchemyError as e:
        # Bookkeeping only: a busy database must not refuse a valid token
        logger.error(f"Failed to update API token last_used_at: {e}")
        await db.rollback()


async def _load_master_token(db: AsyncSession) -> str | None:
    """Fetch the configured master token (or None when unset)."""
    from app.models.setting import Setting
    from sqlalchemy import select
    master_res = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
    master_setting = master_res.scalar_one_or_none()
    return master_setting.value if master_setting else None


def _auth_result(auth_type: str, identity: str) -> dict:
    """Build a successful websocket auth result dict."""
    return {"authenticated": True, "auth_type": auth_type, "identity": identity}


async def _auth_reject(websocket: WebSocket, reason: str = "Unauthorized") -> dict:
    """Close the websocket with 4003 and return a failed auth dict."""
    logger.warning("WebSocket connection rejected: %s", reason)
    await websocket.close(code=4003, reason="Unauthorized")
    return {"authenticated": False}


@dataclass(frozen=True)
class _WsHandshake:
    """A WebSocket being authenticated: the socket, the channel it asks for and the database."""

    db: AsyncSession
    websocket: WebSocket
    endpoint_type: str
    device_id: int | None


async def _auth_logs_query(handshake: _WsHandshake, query_token: str) -> dict | None:
    """Query-token auth for the logs channel (Master-Token only)."""
    master_token = await _load_master_token(handshake.db)
    if master_token and secure_compare(query_token, master_token):
        return _auth_result("master", query_token)
    return await _auth_reject(handshake.websocket, "Invalid master token in query params for logs route.")


async def _auth_agent_query(handshake: _WsHandshake, query_token: str) -> dict | None:
    """Query-token auth for the agent channel (Master-Token or device Agent-Token)."""
    from app.models.agent import AgentToken
    from app.services.agent_tokens import verify_agent_token

    db = handshake.db
    master_token = await _load_master_token(db)
    if master_token and secure_compare(query_token, master_token):
        return _auth_result("master", query_token)

    if handshake.device_id is not None:
        agent_res = await db.execute(
            select(AgentToken).where(
                AgentToken.device_id == handshake.device_id,
                AgentToken.is_active.is_(True)
            )
        )
        agent_token_obj = agent_res.scalar_one_or_none()
        if agent_token_obj and await verify_agent_token(db, agent_token_obj, query_token):
            return _auth_result("agent", query_token)
    return await _auth_reject(handshake.websocket, "Invalid agent/master token or device mismatch in query params.")


async def _auth_scanner_query(handshake: _WsHandshake, query_token: str) -> dict | None:
    """Query-token auth for the scanner channel (Master-Token only)."""
    master_token = await _load_master_token(handshake.db)
    if master_token and secure_compare(query_token, master_token):
        return _auth_result("master", query_token)
    return await _auth_reject(handshake.websocket, "Invalid master token in query params for scanner route.")


async def _auth_query_by_endpoint(handshake: _WsHandshake, query_token: str) -> dict | None:
    """Channel-policy query-token auth for logs/agent/scanner; returns auth dict or None on failure."""
    if handshake.endpoint_type == "logs":
        return await _auth_logs_query(handshake, query_token)
    if handshake.endpoint_type == "agent":
        return await _auth_agent_query(handshake, query_token)
    if handshake.endpoint_type == "scanner":
        return await _auth_scanner_query(handshake, query_token)
    return None


async def _ws_close(websocket: WebSocket, code: int, reason: str, log_message: str) -> dict:
    """Log why a WebSocket is refused, close it and return a failed auth dict."""
    logger.warning(log_message)
    await websocket.close(code=code, reason=reason)
    return {"authenticated": False}


# The scope an API token needs on each WebSocket channel
_WS_TOKEN_SCOPES = {"logs": "settings:read", "scanner": "scanner:read", "agent": "agent:read"}


async def _ws_session_cookie(websocket: WebSocket, cookie_token: str) -> dict:
    """Browser session from the cookie; every channel accepts it (UI clients subscribing)."""
    session = session_store.get_session(cookie_token)
    if not session:
        return await _ws_close(
            websocket, 4003, "Session expired or invalid", "WebSocket connection rejected: Expired or invalid session cookie."
        )
    _warn_on_user_agent_change(session, websocket.headers, channel="WebSocket Session")
    return _auth_result("session", cookie_token)


async def _ws_api_token(handshake: _WsHandshake, db_token) -> dict:
    required_scope = _WS_TOKEN_SCOPES.get(handshake.endpoint_type)
    if required_scope and required_scope not in _token_scopes(db_token):
        return await _ws_close(
            handshake.websocket, 4003, "Insufficient token scopes",
            f"WebSocket API token '{db_token.name}' rejected: missing required scope '{required_scope}'",
        )
    await _touch_api_token(handshake.db, db_token)
    return _auth_result("api_token", f"api_token:{db_token.name}")


async def _ws_query_token(handshake: _WsHandshake, query_token: str) -> dict:
    """``?token=``: an API token, else the master or agent token the channel allows."""
    from app.models.api_token import ApiToken

    h = hashlib.sha256(query_token.encode()).hexdigest()
    db_token = (
        await handshake.db.execute(select(ApiToken).where(ApiToken.token_hash == h, ApiToken.is_active == True))
    ).scalar_one_or_none()
    if db_token:
        return await _ws_api_token(handshake, db_token)

    channel_auth = await _auth_query_by_endpoint(handshake, query_token)
    if channel_auth is not None:
        return channel_auth
    # An invalid query token must not fall through to other channels: reject it.
    return await _ws_close(handshake.websocket, 4003, "Unauthorized", "WebSocket connection rejected: Invalid query token.")


async def _ws_before_setup(handshake: _WsHandshake) -> dict:
    """Before setup only the scanner channel is open, so the wizard can show the first scans."""
    if handshake.endpoint_type == "scanner":
        return _auth_result("setup_bypass", "anonymous")
    return await _ws_close(
        handshake.websocket, 4003, "Setup incomplete",
        f"WebSocket connection rejected: Setup bypass requested on non-scanner route '{handshake.endpoint_type}'.",
    )


async def _ws_legacy_cookie(handshake: _WsHandshake, cookie_token: str | None) -> dict:
    """Deprecated: the master token in the cookie. Anything else counts as missing credentials."""
    if cookie_token:
        master_token = await _load_master_token(handshake.db)
        if master_token and secure_compare(cookie_token, master_token):
            logger.warning(
                "DEPRECATION WARNING: Master-Token used in browser cookie for WebSocket auth. "
                "This legacy path is deprecated and will be removed in a future release."
            )
            return _auth_result("master_legacy", cookie_token)

    return await _ws_close(
        handshake.websocket, 4001, "Missing authentication token", "WebSocket connection rejected: Missing authentication token."
    )


async def _authenticate_websocket_impl(
    websocket: WebSocket,
    endpoint_type: str,
    device_id: int | None,
    db: AsyncSession
) -> dict:
    handshake = _WsHandshake(db, websocket, endpoint_type, device_id)

    # 1. Setup gate
    if not await _setup_completed(db):
        return await _ws_before_setup(handshake)

    cookie_token = websocket.cookies.get("gravitylan_token")
    query_token = websocket.query_params.get("token")

    # Session IDs never travel in the query string
    if query_token and query_token.startswith("session_"):
        return await _ws_close(
            websocket, 4003, "Query-based session auth forbidden",
            "WebSocket connection rejected: Session-IDs via query parameters are strictly forbidden.",
        )

    # 2. Browser session cookie
    if cookie_token and cookie_token.startswith("session_"):
        return await _ws_session_cookie(websocket, cookie_token)

    # 3. Query token per channel policy
    if query_token:
        return await _ws_query_token(handshake, query_token)

    # 4. Deprecated legacy cookie fallback, else missing credentials
    return await _ws_legacy_cookie(handshake, cookie_token)

# Brute-force guard for /login: at most LOGIN_MAX_FAILURES attempts per client IP
# within the sliding window. In memory, which fits the single uvicorn worker.
LOGIN_MAX_FAILURES = 5
LOGIN_FAILURE_WINDOW_SECONDS = 60
_login_attempts: dict[str, list[float]] = {}


def reset_login_rate_limit() -> None:
    """Forget all counted login attempts (used by the test fixtures)."""
    _login_attempts.clear()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _reserve_login_attempt(ip: str) -> int | None:
    """Count a login attempt for ``ip``; returns Retry-After seconds once the limit is hit.

    The attempt is counted before the password is checked (no await in between), so
    parallel requests cannot all pass the check; a successful login clears the count.
    """
    now = time.monotonic()
    window_start = now - LOGIN_FAILURE_WINDOW_SECONDS
    if len(_login_attempts) > 1000:
        # Drop clients whose attempts have all expired so the store stays small
        for stale_ip in [k for k, v in _login_attempts.items() if v[-1] <= window_start]:
            del _login_attempts[stale_ip]

    attempts = [t for t in _login_attempts.get(ip, ()) if t > window_start]
    if len(attempts) >= LOGIN_MAX_FAILURES:
        _login_attempts[ip] = attempts
        return max(1, math.ceil(attempts[0] - window_start))
    attempts.append(now)
    _login_attempts[ip] = attempts
    return None


SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def issue_session_cookie(response: Response, user_agent: str | None) -> None:
    """Create a browser session and attach it as the httpOnly gravitylan_token cookie."""
    session_id = session_store.create_session(user_agent=user_agent)
    response.set_cookie(
        key="gravitylan_token",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
        max_age=SESSION_COOKIE_MAX_AGE,
    )


async def _password_settings(db: AsyncSession) -> tuple[Setting | None, Setting | None]:
    """The master-token row and the admin-password row; either may not exist yet."""
    master_setting = (await db.execute(select(Setting).where(Setting.key == "api.master_token"))).scalar_one_or_none()
    admin_setting = (await db.execute(select(Setting).where(Setting.key == "api.admin_password"))).scalar_one_or_none()
    return master_setting, admin_setting


def _stored_password(master_setting: Setting | None, admin_setting: Setting | None) -> str:
    """The value a password is checked against: the master token counts until a password is set."""
    if admin_setting:
        return admin_setting.value
    return master_setting.value if master_setting else ""


def _password_matches(password: str, stored: str) -> bool:
    """Check against a hash, or against a legacy plaintext value that is not migrated yet."""
    return verify_password(password, stored) if looks_hashed(stored) else secure_compare(password, stored)


async def _save_admin_password(
    db: AsyncSession, admin_setting: Setting | None, password: str, description: str | None = None
) -> None:
    """Hash and store the admin password, creating its row when only the master token exists so far."""
    hashed = hash_password(password)
    if admin_setting:
        admin_setting.value = hashed
    else:
        db.add(Setting(key="api.admin_password", value=hashed, category="system", description=description))
    await db.commit()


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    password: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    """Authenticate and set a secure httpOnly session cookie."""
    client_ip = _client_ip(request)
    retry_after = _reserve_login_attempt(client_ip)
    if retry_after is not None:
        logger.warning("Login blocked for %s: too many failed attempts", client_ip)
        await audit(request, "auth.login", "denied", detail="too many failed attempts", actor="anonymous")
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    master_setting, admin_setting = await _password_settings(db)
    if not master_setting:
        raise HTTPException(status_code=500, detail="System not initialized. Run setup first.")

    required = _stored_password(master_setting, admin_setting)
    if not _password_matches(password, required):
        logger.warning("Login failed: invalid password provided")
        await audit(request, "auth.login", "failed", detail="wrong password", actor="anonymous")
        raise HTTPException(status_code=401, detail="Invalid password")

    logger.info("Login successful, generating lock-free in-memory session")
    _login_attempts.pop(client_ip, None)

    # Auto-migrate to hashed password if it was plaintext
    if not looks_hashed(required):
        logger.info("Migrating legacy plaintext password to hash")
        await _save_admin_password(db, admin_setting, password)

    issue_session_cookie(response, request.headers.get("user-agent"))
    await audit(request, "auth.login", actor="session")
    return {"status": "ok", "message": "Login successful"}

@router.post("/logout")
async def logout(request: Request, response: Response):
    """Clear the authentication cookie and invalidate the in-memory session."""
    cookie_token = request.cookies.get("gravitylan_token")
    if cookie_token and cookie_token.startswith("session_"):
        session_store.delete_session(cookie_token)
    response.delete_cookie(key="gravitylan_token", path="/")
    return {"status": "ok", "message": "Logged out"}

PASSWORD_MIN_LENGTH = 8


class PasswordChange(BaseModel):
    current_password: str = Field(..., max_length=256)
    new_password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=256)


def _is_valid_browser_session(token: str) -> bool:
    return token.startswith("session_") and session_store.get_session(token) is not None


def _ensure_new_password_valid(req: PasswordChange) -> None:
    if req.new_password == req.current_password:
        raise HTTPException(status_code=400, detail="Choose a password that differs from the current one.")
    if not req.new_password.strip():
        raise HTTPException(status_code=400, detail="The new password must not be blank.")


@router.post("/password")
async def change_password(
    req: PasswordChange,
    request: Request,
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Change the admin login password; logs out every other browser session.

    Only a logged-in browser session may do this (not API or master tokens), and the
    current password must be confirmed. Errors are 400, not 401, so the UI does not
    treat a typo as "logged out".
    """
    if not _is_valid_browser_session(token):
        await audit(request, "auth.password", "denied", detail="not a browser session")
        raise HTTPException(status_code=403, detail="Only a logged-in browser session can change the password.")

    master_setting, admin_setting = await _password_settings(db)
    required = _stored_password(master_setting, admin_setting)
    if not required:
        raise HTTPException(status_code=500, detail="System not initialized. Run setup first.")

    if not _password_matches(req.current_password, required):
        logger.warning("Password change rejected: current password is wrong")
        await audit(request, "auth.password", "failed", detail="current password wrong")
        raise HTTPException(status_code=400, detail="The current password is wrong.")
    _ensure_new_password_valid(req)

    await _save_admin_password(
        db, admin_setting, req.new_password, description="Administrator password for dashboard login"
    )

    ended = session_store.delete_all_except(token)
    logger.info("Admin password changed; %d other session(s) logged out", ended)
    await audit(request, "auth.password", detail=f"{ended} other session(s) logged out")
    return {"status": "ok", "other_sessions_ended": ended}


class StepUpRequest(BaseModel):
    password: str = Field(..., max_length=256)
    scope: Literal["remote", "credentials", "instance"]


async def _admin_password_matches(db: AsyncSession, password: str) -> bool:
    master_setting, admin_setting = await _password_settings(db)
    required = _stored_password(master_setting, admin_setting)
    if not required:
        return False
    return _password_matches(password, required)


@router.post("/step-up")
async def step_up(
    req: StepUpRequest,
    request: Request,
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Confirm the admin password again; allows one class of actions to this session for a while (AP-12).

    Wrong passwords count against the same per-address limit as logins. Errors are 400, not 401,
    so the UI does not treat a typo as "logged out".
    """
    session_id = stepup.session_of(request)
    if session_id is None:
        raise HTTPException(status_code=403, detail="Only a logged-in browser session can confirm actions.")
    client_ip = _client_ip(request)
    retry_after = _reserve_login_attempt(client_ip)
    if retry_after is not None:
        await audit(request, "auth.stepup", "denied", detail=f"{req.scope}: too many failed attempts")
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
    if not await _admin_password_matches(db, req.password):
        await audit(request, "auth.stepup", "failed", detail=f"{req.scope}: wrong password")
        raise HTTPException(status_code=400, detail="The password is wrong.")

    _login_attempts.pop(client_ip, None)
    minutes = await stepup.grant_minutes(db)
    stepup.store.grant(session_id, req.scope, minutes * 60)
    await audit(request, "auth.stepup", detail=f"{req.scope}, {minutes} min")
    return {"scope": req.scope, "expires_in": minutes * 60}


@router.get("/step-up")
async def step_up_status(request: Request, token: str = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Seconds left per confirmed class for this browser session, and the grant length in minutes."""
    session_id = stepup.session_of(request)
    return {
        "grants": stepup.store.remaining(session_id) if session_id else {},
        "minutes": await stepup.grant_minutes(db),
    }


@router.post("/check")
async def check_auth(token: str = Depends(get_current_admin)):
    """Check if currently authenticated (via dependency)."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# API Token Management Endpoints
# ---------------------------------------------------------------------------

from app.models.api_token import ApiToken
from app.schemas.api_token import ApiTokenCreate, ApiTokenResponse, ApiTokenCreated

@router.get("/tokens", response_model=list[ApiTokenResponse])
async def list_api_tokens(
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """List all configured read-only API tokens (Admin only)."""
    if token.startswith("api_token:"):
        raise HTTPException(status_code=403, detail="Read-only tokens cannot view or manage other tokens.")
    
    res = await db.execute(select(ApiToken).order_by(ApiToken.created_at.desc()))
    return res.scalars().all()

@router.post("/tokens", response_model=ApiTokenCreated, dependencies=[Depends(require_step_up("credentials"))])
async def create_api_token(
    payload: ApiTokenCreate,
    request: Request,
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Create a new read-only API token (Admin only)."""
    if token.startswith("api_token:"):
        raise HTTPException(status_code=403, detail="Read-only tokens cannot view or manage other tokens.")
    
    raw_token = "gl_pat_" + secrets.token_hex(24)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    prefix = raw_token[:11] + "..."
    scopes_str = ",".join(payload.scopes) if payload.scopes else None

    new_token = ApiToken(
        name=payload.name,
        token_hash=token_hash,
        prefix=prefix,
        is_active=True,
        scopes=scopes_str
    )
    db.add(new_token)
    await db.commit()
    await db.refresh(new_token)
    await audit(request, "auth.token.create", target=new_token.name, detail=scopes_str or "read-only defaults")

    return ApiTokenCreated(
        id=new_token.id,
        name=new_token.name,
        prefix=new_token.prefix,
        is_active=new_token.is_active,
        created_at=new_token.created_at,
        last_used_at=new_token.last_used_at,
        token=raw_token,
        scopes=payload.scopes
    )

@router.delete("/tokens/{token_id}", dependencies=[Depends(require_step_up("credentials"))])
async def delete_api_token(
    token_id: int,
    request: Request,
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Delete (revoke) an API token (Admin only)."""
    if token.startswith("api_token:"):
        raise HTTPException(status_code=403, detail="Read-only tokens cannot view or manage other tokens.")
    
    res = await db.execute(select(ApiToken).where(ApiToken.id == token_id))
    db_token = res.scalar_one_or_none()
    if not db_token:
        raise HTTPException(status_code=404, detail="API Token not found")
    
    await db.delete(db_token)
    await db.commit()
    await audit(request, "auth.token.delete", target=db_token.name)
    return {"status": "ok", "message": "Token revoked successfully"}

@router.get("/me")
async def auth_me(
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Token introspection endpoint returning authorized scopes."""
    if token.startswith("api_token:"):
        name = token.removeprefix("api_token:")
        from app.models.api_token import ApiToken
        res = await db.execute(select(ApiToken).where(ApiToken.name == name))
        db_token = res.scalar_one_or_none()
        if db_token:
            if db_token.scopes:
                scopes = [s.strip() for s in db_token.scopes.split(",") if s.strip()]
            else:
                scopes = [
                    "devices:read", "topology:read", "network:read", "agent:read",
                    "settings:read", "backup:read", "scanner:read"
                ]
            return {"scopes": scopes}
    # Master token or admin browser session has full scopes
    return {"scopes": ["*"]}
