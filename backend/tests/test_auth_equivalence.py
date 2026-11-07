"""Authentication and token scopes give the same answer as before the auth.py refactor.

Frozen copies of _required_scope_for, _enforce_token_scopes, _resolve_admin and
_authenticate_websocket_impl as of 0.7.0-rc.7 are run next to the live functions over every
app route and a grid of cookies, headers, query tokens, setup states and token scopes.
Results, HTTP errors and WebSocket close codes must match exactly.
"""

import hashlib
import itertools
import logging
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import app.api.auth as auth
from app.models.agent import AgentToken
from app.models.api_token import ApiToken
from app.models.device import Device
from app.models.setting import Setting
from app.services.agent_tokens import hash_agent_token
from app.services.auth_service import secure_compare
from app.services.session_service import session_store

logger = logging.getLogger(__name__)

_READONLY_FORBIDDEN_PATHS = ("/api/backup/export", "/api/settings/reset-db")
_READONLY_DEFAULT_SCOPES = {
    "devices:read", "topology:read", "network:read", "agent:read",
    "settings:read", "backup:read", "scanner:read"
}


# --- frozen copies (0.7.0-rc.7) -------------------------------------------------

def _old_required_scope_for(path: str, method: str) -> str | None:
    read_methods = ("GET", "HEAD")
    if path.startswith(("/api/devices", "/api/groups", "/api/services", "/api/interfaces")):
        return "devices:read" if method in read_methods else "devices:write"
    if path.startswith("/api/topology"):
        return "topology:read" if method in read_methods else "topology:write"
    if path.startswith("/api/network"):
        return "network:read" if method in read_methods else "network:write"
    if path.startswith("/api/agent"):
        if path.startswith("/api/agent/download/config") or path.startswith("/api/agent/token") or path.startswith("/api/agent/enroll"):
            return "agent:write"
        return "agent:read" if method in read_methods else "agent:write"
    if path.startswith("/api/settings"):
        return "settings:read" if method in read_methods else "settings:write"
    if path.startswith("/api/backup"):
        return "backup:read" if method in read_methods else "backup:write"
    if path.startswith("/api/scanner"):
        if path.rstrip("/") in ("/api/scanner/live-discovery", "/api/scanner/scan-ip"):
            return "scanner:start"
        return "scanner:read" if method in read_methods else "scanner:start"
    if path.startswith("/api/webhooks"):
        if path.rstrip("/") == "/api/webhooks/test":
            return "settings:write"
        return "settings:read" if method in read_methods else "settings:write"
    if path.startswith("/api/summary") or path.startswith("/api/issues"):
        return "devices:read"
    if path.startswith("/api/auth/tokens") or path.startswith("/api/logs") or path.startswith("/api/audit"):
        return "settings:read" if method in read_methods else "settings:write"
    if path.startswith("/api/agents"):
        return "agent:read" if method in read_methods else "agent:write"
    if path.startswith("/api/notifications") or path.startswith("/api/health"):
        return "devices:read" if method in read_methods else "devices:write"
    return None


def _old_enforce_token_scopes(db_token, conn) -> None:
    if db_token.scopes:
        token_scopes = {s.strip() for s in db_token.scopes.split(",") if s.strip()}
    else:
        token_scopes = _READONLY_DEFAULT_SCOPES

    if conn.scope.get("type") != "http":
        return

    method = conn.method
    path = conn.url.path

    if path in ("/api/auth/check", "/api/auth/me") or path == "/api/ssh/sessions/prepare" or path.startswith(("/api/agent/enroll/", "/api/agent/deploy/", "/api/agent/uninstall/", "/api/agent/patches/")):
        return

    if (
        path in _READONLY_FORBIDDEN_PATHS
        or path.startswith("/api/auth/tokens")
        or path.startswith("/api/ssh")
        or path.startswith("/api/agent/download/config")
        or path.startswith("/api/agent/enroll")
        or path.startswith("/api/agent/adopt")
        or path.startswith("/api/agent/deploy")
        or path.startswith("/api/agent/uninstall")
        or path.startswith("/api/agent/patches")
    ):
        raise HTTPException(
            status_code=403,
            detail="Read-only token is not authorized for this administrative action. Token is not authorized for sensitive administrative actions."
        )

    required_scope = _old_required_scope_for(path, method)
    if required_scope and required_scope not in token_scopes:
        if method not in ("GET", "HEAD"):
            raise HTTPException(
                status_code=403,
                detail=f"Read-only token cannot perform state-modifying actions. Token is missing the required scope '{required_scope}'."
            )
        raise HTTPException(
            status_code=403,
            detail=f"Token is missing the required scope '{required_scope}'."
        )


async def _old_resolve_admin(conn, authorization, token, db) -> str:
    setup_res = await db.execute(select(Setting).where(Setting.key == "setup.complete"))
    setup_setting = setup_res.scalar_one_or_none()
    is_setup_done = setup_setting is not None and setup_setting.value == "true"

    if not is_setup_done:
        if auth._is_setup_wizard_route(conn):
            return "setup_mode"
        raise HTTPException(status_code=403, detail="Initial setup not completed.")

    cookie_token = conn.cookies.get("gravitylan_token")
    if cookie_token:
        if cookie_token.startswith("session_"):
            session = session_store.get_session(cookie_token)
            if session:
                req_ua = conn.headers.get("user-agent")
                if session.user_agent and req_ua and session.user_agent != req_ua:
                    logger.warning("Session User-Agent mismatch: expected '%s', got '%s'", session.user_agent, req_ua)
                return cookie_token
            raise HTTPException(status_code=401, detail="Session expired or invalid")
        else:
            res_token = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
            master_setting = res_token.scalar_one_or_none()
            if master_setting and secure_compare(cookie_token, master_setting.value):
                return cookie_token
            raise HTTPException(status_code=401, detail="Invalid token")

    if authorization and authorization.startswith("Bearer "):
        return await auth._authenticate_bearer(db, authorization, conn)

    if token:
        return await auth._authenticate_query_param(db, token, conn)

    raise HTTPException(status_code=401, detail="Missing authentication token")


async def _old_authenticate_websocket_impl(websocket, endpoint_type, device_id, db) -> dict:
    setup_res = await db.execute(select(Setting).where(Setting.key == "setup.complete"))
    setup_setting = setup_res.scalar_one_or_none()
    is_setup_done = setup_setting is not None and setup_setting.value == "true"

    if not is_setup_done:
        if endpoint_type == "scanner":
            return {"authenticated": True, "auth_type": "setup_bypass", "identity": "anonymous"}
        await websocket.close(code=4003, reason="Setup incomplete")
        return {"authenticated": False}

    cookie_token = websocket.cookies.get("gravitylan_token")
    query_token = websocket.query_params.get("token")

    if query_token and query_token.startswith("session_"):
        await websocket.close(code=4003, reason="Query-based session auth forbidden")
        return {"authenticated": False}

    if cookie_token and cookie_token.startswith("session_"):
        session = session_store.get_session(cookie_token)
        if session:
            return {"authenticated": True, "auth_type": "session", "identity": cookie_token}
        await websocket.close(code=4003, reason="Session expired or invalid")
        return {"authenticated": False}

    if query_token:
        h = hashlib.sha256(query_token.encode()).hexdigest()
        token_res = await db.execute(select(ApiToken).where(ApiToken.token_hash == h, ApiToken.is_active == True))
        db_token = token_res.scalar_one_or_none()

        if db_token:
            if db_token.scopes:
                token_scopes = {s.strip() for s in db_token.scopes.split(",") if s.strip()}
            else:
                token_scopes = _READONLY_DEFAULT_SCOPES
            ws_scope_map = {"logs": "settings:read", "scanner": "scanner:read", "agent": "agent:read"}
            required_scope = ws_scope_map.get(endpoint_type)
            if required_scope and required_scope not in token_scopes:
                await websocket.close(code=4003, reason="Insufficient token scopes")
                return {"authenticated": False}
            await auth._touch_api_token(db, db_token)
            return {"authenticated": True, "auth_type": "api_token", "identity": f"api_token:{db_token.name}"}

        channel_auth = await auth._auth_query_by_endpoint(db, endpoint_type, query_token, device_id, websocket)
        if channel_auth is not None:
            return channel_auth
        await websocket.close(code=4003, reason="Unauthorized")
        return {"authenticated": False}

    if cookie_token:
        master_token = await auth._load_master_token(db)
        if master_token and secure_compare(cookie_token, master_token):
            return {"authenticated": True, "auth_type": "master_legacy", "identity": cookie_token}

    await websocket.close(code=4001, reason="Missing authentication token")
    return {"authenticated": False}


# --- inputs -----------------------------------------------------------------------

METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")


def _router_paths() -> set[str]:
    """Paths of every APIRouter in app.api, read from the routers rather than the assembled app."""
    import importlib
    import pkgutil

    import app.api
    from fastapi import APIRouter

    paths = set()
    for info in pkgutil.iter_modules(app.api.__path__):
        module = importlib.import_module(f"app.api.{info.name}")
        for obj in vars(module).values():
            if isinstance(obj, APIRouter):
                paths.update(getattr(r, "path", "") for r in obj.routes)
    return {p for p in paths if p.startswith("/api")}


def _all_paths() -> list[str]:
    routes = {re.sub(r"\{[^}]+\}", "1", p) for p in _router_paths()}
    extras = {
        "/api/scanner/live-discovery/", "/api/scanner/scan-ip/", "/api/webhooks/test/", "/api/agents",
        "/api/agentsx", "/api/agent/token/rotate", "/api/agent/adopt/1", "/api/agent/enroll", "/api/agent/deploy",
        "/api/ssh", "/api/auth/tokens", "/api/issues/x", "/api/unknown", "/", "/api", "/api/backup/export/",
    }
    return sorted(routes | extras)


TOKEN_SCOPES = [None, "", " , ", "devices:read", "settings:read, scanner:start", "devices:write,agent:write ,backup:read"]


def _http_conn(path, method="GET", kind="http", cookies=None, headers=None):
    scope = {"type": kind}
    if kind == "http":
        scope["method"] = method
    return SimpleNamespace(scope=scope, method=method, url=SimpleNamespace(path=path), cookies=cookies or {}, headers=headers or {})


class _FakeWs:
    def __init__(self, cookie, query, ua):
        self.cookies = {"gravitylan_token": cookie} if cookie else {}
        self.query_params = {"token": query} if query else {}
        self.headers = {"user-agent": ua}
        self.closed = None

    async def close(self, code=1000, reason=None):
        self.closed = (code, reason)


async def _outcome(coro):
    try:
        return ("ok", await coro)
    except HTTPException as exc:
        return ("http", exc.status_code, exc.detail)


def _sync_outcome(fn, *args):
    try:
        return ("ok", fn(*args))
    except HTTPException as exc:
        return ("http", exc.status_code, exc.detail)


# --- the comparisons ---------------------------------------------------------------

def test_required_scope_matches_for_every_route_and_method():
    paths = _all_paths()
    assert len(paths) > 100
    diffs = [(p, m) for p in paths for m in METHODS if auth._required_scope_for(p, m) != _old_required_scope_for(p, m)]
    assert diffs == []


def test_token_scope_enforcement_matches_for_every_route_method_and_scope_set():
    diffs = []
    for path, method, kind, scopes in itertools.product(_all_paths(), METHODS, ("http", "websocket"), TOKEN_SCOPES):
        token = SimpleNamespace(scopes=scopes)
        conn = _http_conn(path, method, kind)
        before = _sync_outcome(_old_enforce_token_scopes, token, conn)
        now = _sync_outcome(auth._enforce_token_scopes, token, conn)
        if before != now:
            diffs.append((path, method, kind, scopes, before, now))
    assert diffs[:3] == []


@pytest.fixture
async def credentials(db):
    dev = Device(ip="192.0.2.77", display_name="agent-host")
    db.add(dev)
    await db.flush()
    db.add_all([
        Setting(key="setup.complete", value="true"),
        Setting(key="api.master_token", value="master-secret"),
        AgentToken(device_id=dev.id, token=hash_agent_token("agent-raw"), is_active=True),
    ])
    for raw, scopes, active in [
        ("tok-full", None, True), ("tok-noscan", "devices:read", True),
        ("tok-logs", "settings:read", True), ("tok-off", None, False),
    ]:
        db.add(ApiToken(name=raw, token_hash=hashlib.sha256(raw.encode()).hexdigest(), prefix=raw[:8], scopes=scopes, is_active=active))
    await db.commit()
    return SimpleNamespace(session=session_store.create_session(user_agent="UA1"), device_id=dev.id)


async def _set_setup(db, done: bool):
    row = (await db.execute(select(Setting).where(Setting.key == "setup.complete"))).scalar_one()
    row.value = "true" if done else "false"
    await db.commit()


@pytest.mark.asyncio
async def test_admin_resolution_matches_for_every_credential_combination(db, credentials):
    cookies = [None, credentials.session, "session_bogus", "master-secret", "wrong"]
    headers = [None, "Bearer master-secret", "Bearer session_x", "Bearer tok-full", "Bearer tok-noscan",
               "Bearer tok-off", "Bearer garbage", "Basic abc"]
    queries = [None, "master-secret", credentials.session, "session_bogus", "garbage"]
    conns = [("http", "GET", "/api/devices"), ("http", "POST", "/api/devices"), ("http", "GET", "/api/scanner/subnets"),
             ("http", "POST", "/api/settings/reset-db"), ("websocket", None, "/api/scanner/ws"), ("websocket", None, "/api/logs/ws")]

    diffs, count = [], 0
    for done in (True, False):
        await _set_setup(db, done)
        for (kind, method, path), cookie, header, query, ua in itertools.product(conns, cookies, headers, queries, ("UA1", "UA2")):
            def conn():
                return _http_conn(path, method, kind, {"gravitylan_token": cookie} if cookie else {}, {"user-agent": ua})
            before = await _outcome(_old_resolve_admin(conn(), header, query, db))
            now = await _outcome(auth._resolve_admin(conn(), header, query, db))
            count += 1
            if before != now:
                diffs.append((done, kind, method, path, cookie, header, query, before, now))
    assert count > 4000
    assert diffs[:3] == []


@pytest.mark.asyncio
async def test_websocket_auth_matches_for_every_credential_combination(db, credentials):
    cookies = [None, credentials.session, "session_bogus", "master-secret", "wrong"]
    queries = [None, "session_x", "master-secret", "tok-full", "tok-noscan", "tok-logs", "tok-off", "agent-raw", "garbage"]

    diffs, count = [], 0
    for done in (True, False):
        await _set_setup(db, done)
        for endpoint, device_id, cookie, query, ua in itertools.product(
            ("logs", "scanner", "agent", "other"), (None, credentials.device_id, 999), cookies, queries, ("UA1", "UA2")
        ):
            old_ws, new_ws = _FakeWs(cookie, query, ua), _FakeWs(cookie, query, ua)
            before = await auth_outcome(_old_authenticate_websocket_impl(old_ws, endpoint, device_id, db), old_ws)
            now = await auth_outcome(auth._authenticate_websocket_impl(new_ws, endpoint, device_id, db), new_ws)
            count += 1
            if before != now:
                diffs.append((done, endpoint, device_id, cookie, query, before, now))
    assert count > 2000
    assert diffs[:3] == []


async def auth_outcome(coro, ws):
    result = await coro
    return result, ws.closed
