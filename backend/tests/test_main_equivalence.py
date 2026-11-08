"""app/main.py: the access-log filter and the GravityUI route answer as before the refactor.

Frozen copies (0.7.0-rc.7) run next to the live code: the filter over access records with and
without arguments and status codes, the GravityUI route over files, nested files, client routes, traversal attempts, sibling folders and missing builds. Plus the log
WebSocket, which had no test.
"""

import logging
import os
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.main as main


# --- frozen copies -----------------------------------------------------------------------

def _old_filter(record):
    status_code = None
    if hasattr(record, "args") and isinstance(record.args, tuple) and len(record.args) >= 5:
        try:
            status_code = int(record.args[4])
        except (ValueError, TypeError):
            pass
    if status_code is not None and status_code >= 400:
        return True
    msg = record.getMessage()
    if status_code is None:
        if any(err_status in msg for err_status in [" 400", " 401", " 403", " 404", " 422", " 500", " 502", " 503", " 504"]):
            return True
    if any(x in msg for x in ["/api/agent/status/", "/api/devices", "/api/groups", "/api/scanner/status", "/api/health", "/api/scanner/ws"]):
        return False
    return True


async def _old_serve_vue_spa(full_path):
    if ".." in full_path or "\\" in full_path or full_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    vue_dir = main._resolve_frontend_vue_dir()
    if not vue_dir.exists():
        raise HTTPException(status_code=404, detail="GravityUI build not found")
    try:
        base_dir = os.path.realpath(str(vue_dir))
        resolved_path = os.path.realpath(os.path.join(base_dir, full_path))
        if not resolved_path.startswith(base_dir) or os.path.commonpath([base_dir, resolved_path]) != base_dir:
            raise HTTPException(status_code=400, detail="Invalid path")
        if os.path.isfile(resolved_path):
            headers = main.INDEX_HEADERS if os.path.basename(resolved_path) == "index.html" else None
            return main.FileResponse(resolved_path, headers=headers)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")
    index_file = os.path.realpath(os.path.join(base_dir, "index.html"))
    if os.path.isfile(index_file):
        return main.FileResponse(index_file, headers=main.INDEX_HEADERS)
    raise HTTPException(status_code=404, detail="GravityUI index.html not found")


# --- access-log filter -------------------------------------------------------------------

TEMPLATE = '%s - "%s %s HTTP/%s" %d'
PATHS = ["/api/health", "/api/devices?x=1", "/api/groups", "/api/agent/status/5", "/api/scanner/status",
         "/api/scanner/ws", "/api/settings", "/frontend-vue/app.js", "/api/devices/1/services"]
STATUSES = [200, 204, 301, 399, 400, 401, 404, 418, 500, 503]


def _records():
    for path in PATHS:
        for status in STATUSES:
            yield logging.LogRecord("uvicorn.access", logging.INFO, "p", 1, TEMPLATE, ("1.2.3.4:5", "GET", path, "1.1", status), None)
            yield logging.LogRecord("uvicorn.access", logging.INFO, "p", 1, f'1.2.3.4:5 - "GET {path} HTTP/1.1" {status}', (), None)
        # args with a status that is no number, and too few args
        yield logging.LogRecord("uvicorn.access", logging.INFO, "p", 1, "%s %s %s %s %s", ("a", "GET", path, "1.1", "n/a"), None)
        yield logging.LogRecord("uvicorn.access", logging.INFO, "p", 1, "%s %s", ("GET", path), None)
    yield logging.LogRecord("uvicorn.access", logging.INFO, "p", 1, "plain message 500 error", None, None)


def test_polling_filter_matches_for_every_record():
    records = list(_records())
    assert len(records) == 199
    diffs = [r.getMessage() for r in records if main.PollingFilter().filter(r) != _old_filter(r)]
    assert diffs == []


# --- SPA routes ---------------------------------------------------------------------------

SPA_PATHS = ["", "index.html", "app.js", "assets/chunk.js", "assets", "settings/network", "deep/a/b/c",
             "../secret.txt", "assets/../../secret.txt", "a\\b", "/etc/passwd", "api/devices", "api/../index.html",
             "apix/route", "%2e%2e/secret.txt", "static_other/x.txt", "missing.css"]


@pytest.fixture
def builds(tmp_path, monkeypatch):
    for name in ("static", "static-vue"):
        build = tmp_path / name
        (build / "assets").mkdir(parents=True)
        (build / "index.html").write_text("<!doctype html>")
        (build / "app.js").write_text("x")
        (build / "assets" / "chunk.js").write_text("y")
    (tmp_path / "static_other").mkdir()
    (tmp_path / "static_other" / "x.txt").write_text("nope")
    (tmp_path / "secret.txt").write_text("secret")
    monkeypatch.setattr(main, "_resolve_frontend_vue_dir", lambda: tmp_path / "static-vue")
    return tmp_path


async def _answer(coro):
    try:
        response = await coro
    except HTTPException as exc:
        return ("http", exc.status_code, exc.detail)
    return ("file", os.path.normcase(response.path), response.headers.get("cache-control"))


@pytest.mark.asyncio
async def test_gravityui_route_matches_for_every_path(builds):
    for path in SPA_PATHS:
        assert await _answer(main.serve_vue_spa(path)) == await _answer(_old_serve_vue_spa(path)), path


@pytest.mark.asyncio
async def test_vue_route_without_build_or_index_matches(builds, monkeypatch):
    (builds / "static-vue" / "index.html").unlink()
    for path in ("settings", "app.js", "../x"):
        assert await _answer(main.serve_vue_spa(path)) == await _answer(_old_serve_vue_spa(path)), path

    monkeypatch.setattr(main, "_resolve_frontend_vue_dir", lambda: builds / "nothing-here")
    for path in ("settings", "app.js", "../x"):
        assert await _answer(main.serve_vue_spa(path)) == await _answer(_old_serve_vue_spa(path)), path


# --- log WebSocket ------------------------------------------------------------------------

def _log_app():
    app = FastAPI()
    app.add_api_websocket_route("/api/logs/ws", main.logs_websocket)
    return app


def test_logs_websocket_sends_history_then_streams_until_the_client_leaves(monkeypatch):
    from app.services import log_streamer

    subscribed = []
    monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", AsyncMock(return_value={"auth_type": "session"}))
    monkeypatch.setattr(log_streamer.log_handler, "get_history", lambda: ["line one", "line two"])
    monkeypatch.setattr(log_streamer.log_handler, "subscribe", lambda ws: subscribed.append(ws))
    monkeypatch.setattr(log_streamer.log_handler, "unsubscribe", lambda ws: subscribed.remove(ws))

    client = TestClient(_log_app())
    with client.websocket_connect("/api/logs/ws") as ws:
        assert [ws.receive_text(), ws.receive_text()] == ["line one", "line two"]
        ws.send_text("ping")
        assert len(subscribed) == 1
    client.close()
    assert subscribed == []


def test_logs_websocket_stops_without_authorization(monkeypatch):
    from app.services import log_streamer
    from starlette.websockets import WebSocketDisconnect

    async def refuse(websocket, **_kw):
        await websocket.close(code=4003)
        return None

    history = []
    monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", refuse)
    monkeypatch.setattr(log_streamer.log_handler, "get_history", lambda: history.append("read") or [])

    with pytest.raises(WebSocketDisconnect):
        with TestClient(_log_app()).websocket_connect("/api/logs/ws"):
            pass
    assert history == []
