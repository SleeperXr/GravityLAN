"""The security matrix: every route declares exactly one access policy, and answers as it says.

- every HTTP method of ``app.openapi()`` and every WebSocket route has exactly one ``policy(...)``;
- ``docs/security-matrix.md`` is what ``scripts/security_matrix.py`` writes from the declarations;
- every route is called as every kind of caller (no login, browser session with and without
  step-up, master token, API token with and without the scope) before and after the first-run
  setup, and the answer (allowed, 401, 403) must match its policy. Endpoints are replaced by a
  stub for this, so only the access decision runs; routes that check a credential of their own
  keep their real endpoint.
"""

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import routing
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from app.api.policy import API_TOKEN, MASTER, SESSION, STATE_POLICY_PASSED, iter_route_policies
from app.database import get_db
from app.main import app
from app.models.api_token import ApiToken
from app.models.setting import Setting
from app.services import stepup
from app.services.session_service import session_store

ROOT = Path(__file__).resolve().parents[2]
MASTER_TOKEN = "matrix-master-token"
STUB_STATUS = 299


def _matrix_script():
    spec = importlib.util.spec_from_file_location("security_matrix", ROOT / "scripts" / "security_matrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENTRIES = list(iter_route_policies(app))
HTTP_ENTRIES = [e for e in ENTRIES if e.method != "WS"]
WS_ENTRIES = [e for e in ENTRIES if e.method == "WS"]


# --- completeness ---------------------------------------------------------------------------------

def test_every_route_and_websocket_declares_exactly_one_policy():
    missing = [(e.method, e.path, e.endpoint, len(e.policies)) for e in ENTRIES if len(e.policies) != 1]
    assert missing == []
    assert len(HTTP_ENTRIES) > 150 and len(WS_ENTRIES) >= 5


def test_openapi_lists_no_route_the_policy_walk_missed():
    # OpenAPI writes "{full_path:path}" as "{full_path}"
    declared = {(e.method, re.sub(r"\{(\w+):\w+\}", r"{\1}", e.path)) for e in HTTP_ENTRIES}
    documented = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    assert documented - declared == set()


def test_websocket_routes_have_websocket_policies_and_http_routes_do_not():
    from fastapi.routing import APIWebSocketRoute

    ws_paths = {
        ctx.path for ctx in routing.iter_route_contexts(app.routes) if isinstance(ctx.original_route, APIWebSocketRoute)
    }
    assert {e.path for e in WS_ENTRIES} == ws_paths
    for e in WS_ENTRIES:
        assert e.policy.channel or e.policy.public, e.path
    for e in HTTP_ENTRIES:
        assert e.policy.channel is None, e.path


@pytest.mark.parametrize("kwargs", [
    {},  # API tokens allowed by default: the scope must be named
    {"scope": "devices:read", "callers": frozenset({"session"})},  # a scope without API tokens
    {"scope": None, "callers": frozenset({"session", "robot"})},
    {"scope": None, "step_up": "sometimes"},
    {"scope": None, "step_up": "remote"},  # remote is for browser sessions only
    {"scope": None, "step_up": "credentials"},  # credentials refuses API tokens
    {"callers": frozenset(), "step_up": "instance"},
    {"callers": frozenset(), "setup": "closed"},
    {"scope": None, "setup": "only"},
    {"scope": None, "agent_token": True},  # a WebSocket option
])
def test_contradictory_declarations_fail_when_the_route_is_defined(kwargs):
    from app.api.policy import policy

    with pytest.raises(ValueError):
        policy(**kwargs)


def test_security_matrix_document_is_current():
    script = _matrix_script()
    assert (ROOT / "docs" / "security-matrix.md").read_text(encoding="utf-8") == script.render(app), (
        "docs/security-matrix.md is out of date: run 'cd backend && python ../scripts/security_matrix.py'"
    )


# --- calling every route as every caller ----------------------------------------------------------

def _url(path: str) -> str:
    path = path.replace("{full_path:path}", "x").replace("{provider}", "unifi")
    return re.sub(r"\{[^}]+\}", "999999", path)


def _token_name(scope: str | None) -> str:
    return f"tok-{scope or 'none'}"


async def _seed(db):
    db.add(Setting(key="api.master_token", value=MASTER_TOKEN))
    db.add(Setting(key="setup.complete", value="false"))
    scopes = {e.policy.scope for e in ENTRIES if e.policy.scope} | {"nothing:here"}
    for scope in scopes | {None}:
        name = _token_name(scope)
        db.add(ApiToken(name=name, token_hash=hashlib.sha256(name.encode()).hexdigest(), prefix=name[:8],
                        scopes=scope or "nothing:here", is_active=True))
    await db.commit()


async def _set_setup(db, done: bool):
    await db.execute(Setting.__table__.update().where(Setting.key == "setup.complete").values(value="true" if done else "false"))
    await db.commit()


def _expected(p, caller: str, done: bool):
    """'ok' (served by the stub), 401, 403, or 'refused' (any 4xx: a route that checks its own credential)."""
    if p.public:
        return "refused" if p.credential else "ok"
    if not done:
        return "ok" if p.setup == "open" else 403
    if caller == "anon":
        return 401
    if caller in ("session", "session_unconfirmed"):
        if p.bearer_only or SESSION not in p.callers:
            return 403
        return 403 if caller == "session_unconfirmed" and p.step_up else "ok"
    if caller == "master":
        return "ok" if MASTER in p.callers else 403
    if caller == "token":
        return "ok" if API_TOKEN in p.callers else 403
    if caller == "token_without_scope":
        return "ok" if API_TOKEN in p.callers and not p.scope else 403
    raise AssertionError(caller)


def _outcome(status: int, want, *, policy_passed: bool = False):
    """Evaluate a matrix response strictly.

    - 5xx is never allowed (neither 'ok' nor 'refused').
    - 'refused' (routes with their own credential check) requires an actual 401/403 denial,
      never a structural 422/404/400.
    - 'ok' requires either the endpoint stub (299) or a 422 validation error, AND proof that
      enforce_policy completed without raising for this exact request (policy_passed=True).
    """
    if status >= 500:
        return status
    if want == "refused":
        return "refused" if status in (401, 403) else status
    if status in (401, 403):
        return status
    if status in (STUB_STATUS, 422) and policy_passed:
        return "ok"
    return status


# Structurally valid payloads for PUBLIC routes that check their own credential (so they reach
# their credential check and return 401/403 instead of failing schema validation with 422).
_VALID_AGENT_REPORT = {
    "agent_version": "0.1.0",
    "timestamp": 1700000000.0,
    "cpu_percent": 1.0,
    "ram": {"total_mb": 1024, "used_mb": 128, "percent": 12.5},
}


def _credential_request_kwargs(entry) -> dict:
    if entry.method == "POST" and entry.path == "/api/agent/report":
        # Structurally valid body + syntactically valid Authorization header with an invalid token
        # so the request reaches the real token verification (401) instead of schema 422.
        return {"json": _VALID_AGENT_REPORT, "headers": {"Authorization": "Bearer invalid-agent-token"}}
    return {}


@pytest_asyncio.fixture
async def matrix_call(db):
    """Issue a single HTTP request and return (Response, policy_passed) using per-request ASGI state."""
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        async def call(
            method: str,
            url: str,
            *,
            headers: dict | None = None,
            cookies: dict | None = None,
            json_body: dict | None = None,
            files: dict | None = None,
        ):
            # Per-request container: zero shared/global state between calls
            observed = {"passed": False}

            async def observing_app(scope, receive, send):
                try:
                    await app(scope, receive, send)
                finally:
                    observed["passed"] = bool(scope.get("state", {}).get(STATE_POLICY_PASSED))

            transport = ASGITransport(app=observing_app)
            async with AsyncClient(transport=transport, base_url="http://test", cookies=cookies or {}) as ac:
                kwargs: dict = {"headers": headers or {}}
                if json_body is not None:
                    kwargs["json"] = json_body
                if files is not None:
                    kwargs["files"] = files
                res = await ac.request(method, url, **kwargs)
            return res, observed["passed"]

        yield call
    finally:
        app.dependency_overrides.clear()


def _request_args(p, caller: str) -> tuple[dict, dict]:
    headers, cookies = {}, {}
    if caller in ("session", "session_unconfirmed"):
        session_id = session_store.create_session(user_agent=None)
        if caller == "session":
            for cls in stepup.CLASSES:
                stepup.store.grant(session_id, cls, 600)
        cookies["gravitylan_token"] = session_id
    elif caller == "master":
        headers["Authorization"] = f"Bearer {MASTER_TOKEN}"
    elif caller == "token":
        headers["Authorization"] = f"Bearer {_token_name(p.scope)}"
    elif caller == "token_without_scope":
        headers["Authorization"] = f"Bearer {_token_name('nothing:here') if p.scope else _token_name(None)}"
    return headers, cookies


CALLERS_AFTER_SETUP = ("anon", "session", "session_unconfirmed", "master", "token", "token_without_scope")
CALLERS_DURING_SETUP = ("anon", "session", "master")


@pytest.fixture
def real_step_up(monkeypatch):
    """conftest grants every step-up; the matrix checks the real rule."""
    monkeypatch.setattr(stepup.store, "is_granted", stepup.StepUpStore.is_granted.__get__(stepup.store))
    stepup.store.clear()
    yield
    stepup.store.clear()


@pytest.fixture
def stub_endpoints(monkeypatch):
    """Endpoints answer STUB_STATUS without running, except routes that check their own credential."""
    real = routing.run_endpoint_function
    own_check = {e.endpoint.rsplit(".", 1)[1] for e in ENTRIES if e.policy.credential}

    async def run(*, dependant, values, is_coroutine):
        if dependant.call.__name__ in own_check:
            return await real(dependant=dependant, values=values, is_coroutine=is_coroutine)
        return JSONResponse({"stub": True}, status_code=STUB_STATUS)

    monkeypatch.setattr(routing, "run_endpoint_function", run)


@pytest.mark.parametrize(
    ("status", "want", "passed", "expected"),
    [
        (500, "ok", True, 500),
        (502, "ok", True, 502),
        (503, "refused", True, 503),
        (404, "ok", True, 404),
        (405, "ok", True, 405),
        (307, "ok", True, 307),
        (422, "ok", False, 422),
        (422, "ok", True, "ok"),
        (STUB_STATUS, "ok", False, STUB_STATUS),
        (STUB_STATUS, "ok", True, "ok"),
        (401, "refused", True, "refused"),
        (403, "refused", True, "refused"),
        (422, "refused", True, 422),
        (404, "refused", True, 404),
        (400, "refused", True, 400),
    ],
)
def test_outcome_rejects_5xx_404_and_unverified_422(status, want, passed, expected):
    assert _outcome(status, want, policy_passed=passed) == expected


@pytest.mark.asyncio
async def test_denied_policy_with_invalid_body_never_counts_as_allowed_422(db, real_step_up, stub_endpoints, matrix_call):
    """A request refused by policy must return 401/403 with policy_passed=False even when its body is invalid."""
    await _seed(db)
    await _set_setup(db, True)

    res_anon, passed_anon = await matrix_call("PUT", "/api/devices/1/mac", json_body={"mac": 123})
    assert res_anon.status_code == 401 and passed_anon is False

    res_ro, passed_ro = await matrix_call(
        "PUT", "/api/devices/1/mac",
        headers={"Authorization": f"Bearer {_token_name('devices:read')}"},
        json_body={"mac": 123},
    )
    assert res_ro.status_code == 403 and passed_ro is False


@pytest.mark.asyncio
async def test_every_http_route_answers_every_caller_as_its_policy_says(db, real_step_up, stub_endpoints, matrix_call):
    await _seed(db)
    mismatches, calls = [], 0
    for done in (False, True):
        await _set_setup(db, done)
        for entry in HTTP_ENTRIES:
            p = entry.policy
            if p.setup == "only" and done:
                continue  # answered by the wizard routes themselves (test_setup_hardening)
            callers = CALLERS_AFTER_SETUP if done else CALLERS_DURING_SETUP
            if p.credential:
                callers = ("anon",)  # without its credential; structurally valid request must get 401/403
            extra = _credential_request_kwargs(entry) if p.credential else {}
            for caller in callers:
                headers, cookies = _request_args(p, caller)
                if extra.get("headers"):
                    headers = {**headers, **extra["headers"]}
                res, policy_passed = await matrix_call(
                    entry.method, _url(entry.path),
                    headers=headers, cookies=cookies, json_body=extra.get("json"),
                )
                calls += 1
                want = _expected(p, caller, done)
                got = _outcome(res.status_code, want, policy_passed=policy_passed)
                if want != got:
                    mismatches.append((
                        done, entry.method, entry.path, caller, want, res.status_code, policy_passed, res.text[:120],
                    ))
                elif caller == "session_unconfirmed" and p.step_up and done:
                    assert res.headers.get("X-Step-Up") == p.step_up, entry.path
                elif want in (401, 403):
                    assert policy_passed is False, (entry.method, entry.path, caller)
    assert calls > 1000
    assert mismatches == []


# --- independent critical security boundaries (not derived from entry.policy) ---------------------

@pytest.mark.asyncio
async def test_critical_security_boundaries_independent_of_policy_declarations(
    db, real_step_up, stub_endpoints, matrix_call, tmp_path, monkeypatch,
):
    """Hardcoded security expectations for high-risk routes using explicitly constructed credentials
    independent of entry.policy, so an accidental policy downgrade cannot pass silently.
    """
    from sqlalchemy import create_engine
    from app.config import settings as app_config
    from app.database import Base

    db.add_all([
        Setting(key="api.master_token", value=MASTER_TOKEN),
        Setting(key="setup.complete", value="true"),
        ApiToken(
            name="indep-write",
            token_hash=hashlib.sha256(b"indep-write").hexdigest(),
            prefix="indep-wr",
            scopes="devices:write,settings:write,agent:write,network:write,scanner:start",
            is_active=True,
        ),
        ApiToken(
            name="indep-readonly",
            token_hash=hashlib.sha256(b"indep-readonly").hexdigest(),
            prefix="indep-ro",
            scopes="devices:read,settings:read,agent:read,network:read,scanner:read",
            is_active=True,
        ),
    ])
    await db.commit()

    confirmed_sid = session_store.create_session(user_agent=None)
    for cls in stepup.CLASSES:
        stepup.store.grant(confirmed_sid, cls, 600)
    unconfirmed_sid = session_store.create_session(user_agent=None)

    callers = {
        "anon": ({}, {}),
        "write_token": ({"Authorization": "Bearer indep-write"}, {}),
        "readonly_token": ({"Authorization": "Bearer indep-readonly"}, {}),
        "master": ({"Authorization": f"Bearer {MASTER_TOKEN}"}, {}),
        "session_unconfirmed": ({}, {"gravitylan_token": unconfirmed_sid}),
        "session_confirmed": ({}, {"gravitylan_token": confirmed_sid}),
    }

    # (method, path, caller, expected_status_or_ok, expected_step_up_header)
    boundaries = [
        # Instance-critical routes: no anon, no API token (even with write scopes), step-up=instance
        ("GET", "/api/backup/export", "anon", 401, None),
        ("GET", "/api/backup/export", "write_token", 403, None),
        ("GET", "/api/backup/export", "session_unconfirmed", 403, "instance"),
        ("GET", "/api/backup/export", "session_confirmed", "ok", None),
        ("GET", "/api/backup/export", "master", "ok", None),
        ("POST", "/api/backup/import", "anon", 401, None),
        ("POST", "/api/backup/import", "write_token", 403, None),
        ("POST", "/api/backup/import", "session_unconfirmed", 403, "instance"),
        ("POST", "/api/backup/import", "session_confirmed", "ok", None),
        ("POST", "/api/settings/reset-db", "anon", 401, None),
        ("POST", "/api/settings/reset-db", "write_token", 403, None),
        ("POST", "/api/settings/reset-db", "session_unconfirmed", 403, "instance"),
        # Remote execution / agent adoption: browser session only (no anon, no API token, no master), step-up=remote
        ("POST", "/api/agent/deploy/1", "anon", 401, None),
        ("POST", "/api/agent/deploy/1", "write_token", 403, None),
        ("POST", "/api/agent/deploy/1", "master", 403, None),
        ("POST", "/api/agent/deploy/1", "session_unconfirmed", 403, "remote"),
        ("POST", "/api/agent/deploy/1", "session_confirmed", "ok", None),
        ("POST", "/api/agent/uninstall/1", "master", 403, None),
        ("POST", "/api/agent/adopt/1", "master", 403, None),
        ("POST", "/api/agent/adopt/1", "write_token", 403, None),
        ("POST", "/api/agent/adopt/1", "session_unconfirmed", 403, "remote"),
        ("POST", "/api/agent/adopt/1", "session_confirmed", "ok", None),
        ("POST", "/api/ssh/sessions/prepare", "master", 403, None),
        ("POST", "/api/ssh/sessions/prepare", "write_token", 403, None),
        # Credentials management: no API token, step-up=credentials
        ("POST", "/api/auth/tokens", "anon", 401, None),
        ("POST", "/api/auth/tokens", "write_token", 403, None),
        ("POST", "/api/auth/tokens", "session_unconfirmed", 403, "credentials"),
        ("POST", "/api/auth/tokens", "session_confirmed", "ok", None),
        # Read-only API token must not write devices
        ("GET", "/api/devices", "readonly_token", "ok", None),
        ("PUT", "/api/devices/1/mac", "readonly_token", 403, None),
        ("PUT", "/api/devices/1/mac", "write_token", "ok", None),
        ("DELETE", "/api/devices/1", "readonly_token", 403, None),
        ("DELETE", "/api/devices/1", "write_token", "ok", None),
    ]

    for method, path, caller_name, want, want_step_up in boundaries:
        headers, cookies = callers[caller_name]
        res, passed = await matrix_call(method, path, headers=headers, cookies=cookies)
        got = _outcome(res.status_code, want, policy_passed=passed)
        assert got == want, (method, path, caller_name, want, res.status_code, passed, res.text[:120])
        if want_step_up is not None:
            assert res.headers.get("X-Step-Up") == want_step_up, (method, path, caller_name)

    # Setup gate check: closed routes are 403 during setup; /api/setup/restore accepts a structurally
    # valid backup during setup (200) and refuses it with 403 once setup is complete.
    backup_file = tmp_path / "setup_boundary.db"
    sync_engine = create_engine(f"sqlite:///{backup_file}")
    Base.metadata.create_all(sync_engine, tables=[t for t in Base.metadata.sorted_tables if t.schema is None])
    sync_engine.dispose()
    monkeypatch.setattr(app_config, "database_url", f"sqlite+aiosqlite:///{backup_file}")
    valid_backup = json.dumps({"settings": [{"key": "scan_interval", "value": "15"}]}).encode()

    await _set_setup(db, False)
    res_closed, passed_closed = await matrix_call("GET", "/api/backup/export")
    assert res_closed.status_code == 403 and passed_closed is False

    # Restore real endpoint function for POST /api/setup/restore to verify real 200 vs 403 behavior
    monkeypatch.undo()
    monkeypatch.setattr(app_config, "database_url", f"sqlite+aiosqlite:///{backup_file}")
    res_open, passed_open = await matrix_call(
        "POST", "/api/setup/restore", files={"file": ("backup.json", valid_backup, "application/json")},
    )
    assert res_open.status_code == 200 and passed_open is True

    await _set_setup(db, True)
    res_done, _ = await matrix_call(
        "POST", "/api/setup/restore", files={"file": ("backup.json", valid_backup, "application/json")},
    )
    assert res_done.status_code == 403


# --- deterministic catch-all route (with and without frontend build) ------------------------------

@pytest.mark.asyncio
async def test_catch_all_route_with_and_without_frontend_build(matrix_call, tmp_path, monkeypatch):
    """Real app routing for /{full_path:path} with simulated build present vs absent."""
    import app.main as main_mod

    build_dir = tmp_path / "dist"
    build_dir.mkdir()
    (build_dir / "index.html").write_text("<!doctype html><title>GravityUI</title>", encoding="utf-8")

    # 1. With build present: legacy UI paths redirect to /frontend-vue/, no redirect loop, unknown API stays 404
    monkeypatch.setattr(main_mod, "_resolve_frontend_vue_dir", lambda: build_dir)
    res_ui, passed_ui = await matrix_call("GET", "/devices")
    assert res_ui.status_code == 307 and res_ui.headers["location"] == "/frontend-vue/" and passed_ui is True

    res_root, _ = await matrix_call("GET", "/frontend-vue/")
    assert res_root.status_code == 200

    res_api_404, _ = await matrix_call("GET", "/api/does-not-exist")
    assert res_api_404.status_code == 404

    res_health, _ = await matrix_call("GET", "/api/health")
    assert res_health.status_code == 200

    # 2. Without build present: fallback returns 404 (not 307), unknown API stays 404, known routes keep working
    missing_dir = tmp_path / "no-dist"
    monkeypatch.setattr(main_mod, "_resolve_frontend_vue_dir", lambda: missing_dir)
    res_ui_missing, passed_missing = await matrix_call("GET", "/devices")
    assert res_ui_missing.status_code == 404 and passed_missing is True

    res_api_missing, _ = await matrix_call("GET", "/api/does-not-exist")
    assert res_api_missing.status_code == 404

    res_health_missing, _ = await matrix_call("GET", "/api/health")
    assert res_health_missing.status_code == 200

    res_post_unknown, _ = await matrix_call("POST", "/unknown-non-api")
    assert res_post_unknown.status_code == 405


# --- WebSockets -------------------------------------------------------------------------------------

@pytest.fixture
def ws_database(monkeypatch, tmp_path):
    """A file database the WebSocket handshakes (TestClient's own event loop) can open."""
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from app.database import Base
    from app.models.agent import AgentToken
    from app.models.device import Device
    from app.services.agent_tokens import hash_agent_token

    path = tmp_path / "ws.db"
    sync_engine = create_engine(f"sqlite:///{path}")
    tables = [table for table in Base.metadata.sorted_tables if table.schema is None]
    Base.metadata.create_all(sync_engine, tables=tables)
    with Session(sync_engine) as s:
        s.add_all([Setting(key="api.master_token", value=MASTER_TOKEN), Setting(key="setup.complete", value="true")])
        device = Device(ip="192.0.2.5", display_name="ws-device")
        s.add(device)
        s.flush()
        s.add(AgentToken(device_id=device.id, token=hash_agent_token("agent-raw"), is_active=True))
        for scope in ("settings:read", "scanner:read", "agent:read", "nothing:here"):
            name = _token_name(scope)
            s.add(ApiToken(name=name, token_hash=hashlib.sha256(name.encode()).hexdigest(), prefix=name[:8],
                           scopes=scope, is_active=True))
        s.commit()
        device_id = device.id
    sync_engine.dispose()

    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
    monkeypatch.setattr("app.database.async_session", async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))

    def set_setup(done: bool):
        e = create_engine(f"sqlite:///{path}")
        with e.begin() as conn:
            conn.execute(Setting.__table__.update().where(Setting.key == "setup.complete").values(value="true" if done else "false"))
        e.dispose()

    return device_id, set_setup


def _ws_connect(path: str, cookie: str | None = None, query: str = ""):
    client = TestClient(app)
    if cookie:
        client.cookies.set("gravitylan_token", cookie)
    try:
        with client.websocket_connect(path + query):
            return "ok"
    except WebSocketDisconnect as exc:
        return exc.code


WS_CALLERS = ("anon", "session", "master_query", "master_cookie", "token_query", "token_without_scope", "agent_token")


def _ws_expected(p, caller: str, done: bool) -> str:
    if not done:
        return "ok" if p.setup == "open" else "refused"
    allowed = {
        "anon": False,
        "session": SESSION in p.callers,
        "master_query": MASTER in p.callers,
        "master_cookie": MASTER in p.callers,
        "token_query": API_TOKEN in p.callers,
        "token_without_scope": API_TOKEN in p.callers and not p.scope,
        "agent_token": p.agent_token,
    }[caller]
    return "ok" if allowed else "refused"


def _ws_credentials(p, caller: str) -> tuple[str | None, str]:
    """(session cookie, query string) a caller of this kind brings to the handshake."""
    if caller == "session":
        return session_store.create_session(user_agent=None), ""
    query_tokens = {
        "anon": None,
        "master_cookie": None,
        "master_query": MASTER_TOKEN,
        "token_query": _token_name(p.scope or "settings:read"),
        "token_without_scope": _token_name("nothing:here"),
        "agent_token": "agent-raw",
    }
    token = query_tokens[caller]
    return (MASTER_TOKEN if caller == "master_cookie" else None), (f"?token={token}" if token else "")


def test_every_websocket_answers_every_caller_as_its_policy_says(ws_database, monkeypatch):
    device_id, set_setup = ws_database
    # Past the policy the patch channel checks its one-shot token (before accepting); the matrix only
    # asks whether the handshake got that far, so that check just records it (test_agent_patch_ws covers it)
    import app.api.agent_patches as patches

    reached = []

    async def no_session(websocket, device_id):
        reached.append(device_id)
        return None

    monkeypatch.setattr(patches, "_consume_patch_session", no_session)

    mismatches = []
    for done in (True, False):
        set_setup(done)
        for entry in WS_ENTRIES:
            p = entry.policy
            if p.public:
                continue  # the SSH terminal checks its cookie or ticket itself (test_ssh_api)
            path = entry.path.replace("{device_id}", str(device_id))
            for caller in WS_CALLERS if done else ("anon",):
                cookie, query = _ws_credentials(p, caller)
                # "ok": the policy let the handshake through (accepted, or handed to the patch token check)
                reached.clear()
                got = "ok" if _ws_connect(path, cookie, query) == "ok" or reached else "refused"
                want = _ws_expected(p, caller, done)
                if want != got:
                    mismatches.append((done, path, caller, want, got))
    assert mismatches == []
