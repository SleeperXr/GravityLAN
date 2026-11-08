"""Edges of the auth API (app/api/auth.py): the WebSocket wrappers, a failing last-used update,
the login limiter's clean-up, passwords that are not set up yet and token routes reached directly."""

import hashlib
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import app.api.auth as auth
from app.models.api_token import ApiToken
from app.models.setting import Setting
from app.schemas.api_token import ApiTokenCreate
from app.services.auth_service import verify_password
from app.services.session_service import session_store

NEW_PASSWORD = "new-password-1"


class _Ws:
    def __init__(self, query=None):
        self.cookies = {}
        self.query_params = {"token": query} if query else {}
        self.headers = {}
        self.closed = None

    async def close(self, code=1000, reason=None):
        self.closed = (code, reason)


class _SessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


async def _add_settings(db, **values):
    for key, value in values.items():
        db.add(Setting(key=key.replace("__", "."), value=value))
    await db.commit()


async def _admin_password_row(db):
    return (await db.execute(select(Setting).where(Setting.key == "api.admin_password"))).scalar_one()


def _log_in(client):
    client.cookies.set("gravitylan_token", session_store.create_session(user_agent="UA"))


# --- WebSocket wrappers -------------------------------------------------------------

@pytest.mark.asyncio
async def test_websocket_opens_its_own_session_when_none_is_passed(db, monkeypatch):
    await _add_settings(db, setup__complete="true", api__master_token="master-secret")
    monkeypatch.setattr("app.database.async_session", lambda: _SessionContext(db))

    info = await auth.authenticate_websocket(_Ws(query="master-secret"), "logs")

    assert info == {"authenticated": True, "auth_type": "master", "identity": "master-secret"}


@pytest.mark.asyncio
async def test_authorized_websocket_returns_nothing_after_a_failed_login(monkeypatch):
    ws = _Ws()
    monkeypatch.setattr(auth, "authenticate_websocket", AsyncMock(return_value={"authenticated": False}))

    assert await auth.authenticate_websocket_authorized(ws, "logs") is None
    assert ws.closed is None  # authenticate_websocket has already closed it


@pytest.mark.asyncio
async def test_authorized_websocket_closes_a_level_that_is_not_allowed(monkeypatch):
    ws = _Ws()
    info = {"authenticated": True, "auth_type": "agent", "identity": "agent-raw"}
    monkeypatch.setattr(auth, "authenticate_websocket", AsyncMock(return_value=info))

    assert await auth.authenticate_websocket_authorized(ws, "agent", device_id=7) is None
    assert ws.closed == (4003, "Unauthorized access level")


@pytest.mark.asyncio
async def test_authorized_websocket_hands_back_an_allowed_client(monkeypatch):
    ws = _Ws()
    info = {"authenticated": True, "auth_type": "agent", "identity": "agent-raw"}
    authenticate = AsyncMock(return_value=info)
    monkeypatch.setattr(auth, "authenticate_websocket", authenticate)

    assert await auth.authenticate_websocket_authorized(ws, "agent", allowed_levels=("agent",), device_id=7) == info
    authenticate.assert_awaited_once_with(ws, endpoint_type="agent", device_id=7)
    assert ws.closed is None


@pytest.mark.asyncio
async def test_refused_token_is_named_in_the_log_even_with_a_percent_sign(db, caplog):
    await _add_settings(db, setup__complete="true", api__master_token="master-secret")
    raw = "tok-scoped"
    db.add(ApiToken(name="100% reader", token_hash=hashlib.sha256(raw.encode()).hexdigest(), prefix="tok", scopes="devices:read"))
    await db.commit()

    ws = _Ws(query=raw)
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        result = await auth._authenticate_websocket_impl(ws, "logs", None, db)

    assert result == {"authenticated": False}
    assert ws.closed == (4003, "Insufficient token scopes")
    assert "WebSocket API token '100% reader' rejected: missing required scope 'settings:read'" in caplog.messages


@pytest.mark.asyncio
async def test_channel_refused_before_setup_is_named_in_the_log(db, caplog):
    ws = _Ws()
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        result = await auth._authenticate_websocket_impl(ws, "logs", None, db)

    assert result == {"authenticated": False}
    assert ws.closed == (4003, "Setup incomplete")
    assert "WebSocket connection rejected: Setup bypass requested on non-scanner route 'logs'." in caplog.messages


# --- last-used bookkeeping ----------------------------------------------------------

@pytest.mark.asyncio
async def test_a_database_failure_in_the_last_used_update_does_not_refuse_the_token():
    db = SimpleNamespace(commit=AsyncMock(side_effect=OperationalError("UPDATE", {}, Exception("locked"))), rollback=AsyncMock())

    await auth._touch_api_token(db, SimpleNamespace(last_used_at=None))

    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_programming_error_in_the_last_used_update_is_not_hidden():
    db = SimpleNamespace(commit=AsyncMock(side_effect=TypeError("bug")), rollback=AsyncMock())

    with pytest.raises(TypeError):
        await auth._touch_api_token(db, SimpleNamespace(last_used_at=None))

    db.rollback.assert_not_awaited()


# --- login limiter and stored passwords ---------------------------------------------

def test_login_limiter_forgets_clients_whose_attempts_have_expired():
    expired = time.monotonic() - auth.LOGIN_FAILURE_WINDOW_SECONDS - 1
    for index in range(1001):
        auth._login_attempts[f"stale-{index}"] = [expired]
    auth._login_attempts["active"] = [time.monotonic()]

    assert auth._reserve_login_attempt("new-client") is None
    assert set(auth._login_attempts) == {"active", "new-client"}


@pytest.mark.asyncio
async def test_login_needs_a_master_token_even_with_a_password_set(client, db):
    await _add_settings(db, api__admin_password="secret")

    response = await client.post("/api/auth/login", json={"password": "secret"})

    assert response.status_code == 500


@pytest.mark.asyncio
async def test_login_with_the_plaintext_master_token_stores_a_hashed_password(client, db):
    await _add_settings(db, setup__complete="true", api__master_token="master-plain")

    response = await client.post("/api/auth/login", json={"password": "master-plain"})

    assert response.status_code == 200
    row = await _admin_password_row(db)
    assert verify_password("master-plain", row.value)
    assert (row.category, row.description) == ("system", None)


@pytest.mark.asyncio
async def test_password_change_fails_cleanly_when_nothing_is_configured(client, db):
    await _add_settings(db, setup__complete="true")
    _log_in(client)

    response = await client.post("/api/auth/password", json={"current_password": "x", "new_password": NEW_PASSWORD})

    assert response.status_code == 500


@pytest.mark.asyncio
async def test_password_change_refuses_a_blank_password(client, db):
    await _add_settings(db, setup__complete="true", api__master_token="master-plain")
    _log_in(client)

    response = await client.post("/api/auth/password", json={"current_password": "master-plain", "new_password": " " * 8})

    assert response.status_code == 400
    assert response.json()["detail"] == "The new password must not be blank."


@pytest.mark.asyncio
async def test_password_change_creates_the_row_when_only_the_master_token_exists(client, db):
    await _add_settings(db, setup__complete="true", api__master_token="master-plain")
    _log_in(client)

    response = await client.post("/api/auth/password", json={"current_password": "master-plain", "new_password": NEW_PASSWORD})

    assert response.status_code == 200
    row = await _admin_password_row(db)
    assert verify_password(NEW_PASSWORD, row.value)
    assert (row.category, row.description) == ("system", "Administrator password for dashboard login")


@pytest.mark.asyncio
async def test_step_up_password_check_is_false_when_nothing_is_configured(db):
    assert await auth._admin_password_matches(db, "anything") is False


# --- token routes reached directly --------------------------------------------------

@pytest.mark.asyncio
async def test_token_routes_refuse_an_api_token_that_reaches_them(db):
    caller = "api_token:reader"
    request = SimpleNamespace()
    calls = (
        auth.list_api_tokens(caller, db),
        auth.create_api_token(ApiTokenCreate(name="new"), request, caller, db),
        auth.delete_api_token(1, request, caller, db),
    )
    for call in calls:
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_deleting_an_unknown_token_is_a_404(db):
    with pytest.raises(HTTPException) as exc:
        await auth.delete_api_token(404, SimpleNamespace(), "session_admin", db)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_me_reports_the_read_only_defaults_for_a_token_without_scopes(db):
    db.add(ApiToken(name="reader", token_hash="hash", prefix="gl_pat", scopes=None))
    await db.commit()

    assert await auth.auth_me("api_token:reader", db) == {
        "scopes": ["devices:read", "topology:read", "network:read", "agent:read", "settings:read", "backup:read", "scanner:read"]
    }
