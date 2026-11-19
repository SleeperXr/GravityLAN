"""Cross-site WebSocket handshakes, security headers, and the SQLite-only backup/reset."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import auth
from app.api.auth import websocket_origin_allowed

HEADERS = {"Authorization": "Bearer test-admin-token-12345"}


def _ws(**headers):
    return SimpleNamespace(headers={k.replace("_", "-"): v for k, v in headers.items()})


@pytest.mark.parametrize("headers", [
    {},  # scripts and agents send no Origin
    {"origin": "http://192.168.1.10:8000", "host": "192.168.1.10:8000"},
    {"origin": "HTTP://GravityLAN.local:8000/", "host": "gravitylan.local:8000"},
    {"origin": "https://gravity.example.com", "host": "gravity.example.com"},
    {"origin": "https://gravity.example.com", "host": "gravity.example.com:443"},
    {"origin": "http://[fd00::5]:8000", "host": "[fd00::5]:8000"},
    # Reverse proxy that rewrites Host to the upstream and passes the browser's host along
    {"origin": "https://gravity.example.com", "host": "127.0.0.1:8000", "x_forwarded_host": "gravity.example.com"},
])
def test_same_origin_and_originless_handshakes_are_allowed(headers):
    assert websocket_origin_allowed(_ws(**headers))


@pytest.mark.parametrize("headers", [
    {"origin": "https://evil.example", "host": "192.168.1.10:8000"},
    {"origin": "http://192.168.1.10:9000", "host": "192.168.1.10:8000"},
    {"origin": "https://192.168.1.10:8000", "host": "192.168.1.10"},
    {"origin": "null", "host": "192.168.1.10:8000"},
    {"origin": "file://", "host": "192.168.1.10:8000"},
    {"origin": "http://192.168.1.10.evil.example:8000", "host": "192.168.1.10:8000"},
])
def test_cross_site_handshakes_are_refused(headers):
    assert not websocket_origin_allowed(_ws(**headers))


def test_configured_cors_origins_are_allowed(monkeypatch):
    monkeypatch.setattr(auth.settings, "cors_origins", ["http://localhost:5173"])
    assert websocket_origin_allowed(_ws(origin="http://localhost:5173", host="127.0.0.1:8000"))
    assert not websocket_origin_allowed(_ws(origin="http://localhost:5174", host="127.0.0.1:8000"))


def _ws_app():
    from app import main
    from app.api.ssh import ws_router

    app = FastAPI()
    app.add_api_websocket_route("/api/logs/ws", main.logs_websocket)
    app.include_router(ws_router)
    return app


def test_cross_site_logs_websocket_is_closed_before_authentication(monkeypatch):
    db_opened = AsyncMock()
    monkeypatch.setattr("app.database.async_session", db_opened)

    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(_ws_app()).websocket_connect(
            "/api/logs/ws", headers={"origin": "https://evil.example"},
        ):
            pass
    assert exc.value.code == 4003
    db_opened.assert_not_called()


def test_cross_site_terminal_websocket_is_refused_on_the_ticket_path(monkeypatch):
    consumed = []
    monkeypatch.setattr("app.api.ssh.consume_ticket", lambda *a, **kw: consumed.append(a))

    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(_ws_app()).websocket_connect(
            "/api/ssh/terminal?ticket=abc", headers={"origin": "https://evil.example"},
        ):
            pass
    assert exc.value.code == 4003
    assert consumed == []


@pytest.mark.asyncio
async def test_responses_carry_security_headers(client):
    res = await client.get("/api/health")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["x-frame-options"] == "DENY"
    assert res.headers["referrer-policy"] == "same-origin"
    assert "frame-ancestors 'none'" in res.headers["content-security-policy"]


@pytest.fixture
def external_database(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://db/gravitylan")


@pytest.mark.asyncio
async def test_backup_export_and_import_refuse_an_external_database(client, admin_token, external_database):
    res = await client.get("/api/backup/export", headers=HEADERS)
    assert res.status_code == 400
    assert "SQLite" in res.json()["detail"]

    res = await client.post(
        "/api/backup/import", headers=HEADERS,
        files={"file": ("backup.json", b"{}", "application/json")},
    )
    assert res.status_code == 400
    assert "SQLite" in res.json()["detail"]


@pytest.mark.asyncio
async def test_reset_refuses_an_external_database_before_stopping_the_scheduler(
    client, admin_token, external_database, monkeypatch,
):
    from app.scanner.scheduler import scheduler

    stop = AsyncMock()
    monkeypatch.setattr(scheduler, "stop", stop)
    res = await client.post("/api/settings/reset-db", headers=HEADERS)
    assert res.status_code == 400
    assert "SQLite" in res.json()["detail"]
    stop.assert_not_called()
