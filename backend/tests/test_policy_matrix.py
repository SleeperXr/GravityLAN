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
import re
from pathlib import Path

import pytest
from fastapi import routing
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.policy import API_TOKEN, MASTER, SESSION, iter_route_policies
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


def _outcome(status: int, want):
    if want == "refused":
        return "refused" if 400 <= status < 500 else status
    if status in (401, 403):
        return status
    return "ok"  # served by the stub (or a 404/422 the request itself caused)


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


@pytest.mark.asyncio
async def test_every_http_route_answers_every_caller_as_its_policy_says(client, db, real_step_up, stub_endpoints):
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
                callers = ("anon",)  # without its credential; the route's own tests cover the rest
            for caller in callers:
                headers, cookies = _request_args(p, caller)
                client.cookies.clear()
                for name, value in cookies.items():
                    client.cookies.set(name, value)
                res = await client.request(entry.method, _url(entry.path), headers=headers)
                calls += 1
                want = _expected(p, caller, done)
                got = _outcome(res.status_code, want)
                if want != got:
                    mismatches.append((done, entry.method, entry.path, caller, want, res.status_code, res.text[:120]))
                elif caller == "session_unconfirmed" and p.step_up and done:
                    assert res.headers.get("X-Step-Up") == p.step_up, entry.path
    client.cookies.clear()
    assert calls > 1000
    assert mismatches == []


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


def test_every_websocket_answers_every_caller_as_its_policy_says(ws_database, monkeypatch):
    device_id, set_setup = ws_database
    # Past the policy the patch channel wants its one-shot token; the matrix only asks whether the
    # handshake got that far, so the token check is skipped here (test_agent_patch_ws covers it)
    import app.api.agent_patches as patches

    async def no_session(websocket, device_id):
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
                cookie, query = None, ""
                if caller == "session":
                    cookie = session_store.create_session(user_agent=None)
                elif caller == "master_cookie":
                    cookie = MASTER_TOKEN
                elif caller == "master_query":
                    query = f"?token={MASTER_TOKEN}"
                elif caller == "token_query":
                    query = f"?token={_token_name(p.scope or 'settings:read')}"
                elif caller == "token_without_scope":
                    query = f"?token={_token_name('nothing:here')}"
                elif caller == "agent_token":
                    query = "?token=agent-raw"
                # "ok": the handshake was accepted (what the endpoint does afterwards does not matter here)
                got = "ok" if _ws_connect(path, cookie, query) == "ok" else "refused"
                want = _ws_expected(p, caller, done)
                if want != got:
                    mismatches.append((done, path, caller, want, got))
    assert mismatches == []
