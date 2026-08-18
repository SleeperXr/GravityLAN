"""Tests for the agent patch-run WebSocket flow (app/api/agent.py).

Covers the one-shot session-token handling and the end-to-end patch-run
websocket orchestration, using fakes for the WebSocket, SSH probe, and
SSH command streaming. The last two agent bug-fixes lived in this flow
(apt cache refresh, SSH PTY hang), so it is protected here on purpose.
"""

import asyncio
import time

import pytest

import app.api.agent as agent_module
from app.api.agent import _consume_patch_session, _temp_patch_tokens


class FakeWebSocket:
    """Minimal WebSocket double exposing the surface run_patches_websocket uses."""

    def __init__(self, query_params=None):
        self.query_params = query_params or {}
        self._sent = []
        self._accepted = False
        self.close_code = None
        self.close_reason = None

    async def accept(self):
        self._accepted = True

    async def send_text(self, text):
        self._sent.append(text)

    async def close(self, code=1000, reason=None):
        self.close_code = code
        self.close_reason = reason

    @property
    def sent(self):
        return self._sent


@pytest.fixture(autouse=True)
def clear_patch_tokens():
    _temp_patch_tokens.clear()
    yield
    _temp_patch_tokens.clear()


def _seed_patch_token(device_id=5, mode="full", host_ip="192.168.1.50"):
    token = "patch_tok_testtoken123"
    _temp_patch_tokens[token] = {
        "device_id": device_id,
        "host_ip": host_ip,
        "ssh_user": "root",
        "ssh_password": None,
        "ssh_key": None,
        "ssh_port": 22,
        "mode": mode,
        "created_at": time.time(),
    }
    return token


async def _auth_ok(websocket, endpoint_type, device_id=None, allowed_levels=()):
    return {"authenticated": True, "auth_type": "session", "identity": "session"}


# --- _consume_patch_session -------------------------------------------------

@pytest.mark.asyncio
async def test_consume_patch_session_valid():
    token = _seed_patch_token(device_id=5)
    ws = FakeWebSocket(query_params={"patch_token": token})
    session = _consume_patch_session(ws, 5)
    assert session is not None
    assert session["device_id"] == 5
    assert session["mode"] == "full"
    # one-shot: token is consumed
    assert token not in _temp_patch_tokens


@pytest.mark.asyncio
async def test_consume_patch_session_missing_token():
    ws = FakeWebSocket(query_params={})
    assert _consume_patch_session(ws, 5) is None


@pytest.mark.asyncio
async def test_consume_patch_session_invalid_token():
    ws = FakeWebSocket(query_params={"patch_token": "patch_tok_unknown"})
    assert _consume_patch_session(ws, 5) is None


@pytest.mark.asyncio
async def test_consume_patch_session_device_mismatch():
    token = _seed_patch_token(device_id=5)
    ws = FakeWebSocket(query_params={"patch_token": token})
    # device_id 99 != session's 5 -> rejected, token consumed
    assert _consume_patch_session(ws, 99) is None
    assert token not in _temp_patch_tokens


# --- run_patches_websocket --------------------------------------------------

@pytest.mark.asyncio
async def test_run_patches_websocket_success(monkeypatch):
    token = _seed_patch_token(device_id=5, mode="full")

    async def fake_probe(host_ip, ssh_user, ssh_password, ssh_key, ssh_port):
        return {"patch_manager": "apt", "packages": [], "error": None}

    async def fake_run_stream(*, host_ip, ssh_user, ssh_password, ssh_key, ssh_port, command, output_callback):
        output_callback("stdout line")
        return True, "Success"

    monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", _auth_ok)
    monkeypatch.setattr(agent_module, "list_device_updates", fake_probe)
    monkeypatch.setattr(agent_module, "run_ssh_command_stream", fake_run_stream)
    monkeypatch.setattr(agent_module, "_clear_device_patch_state", lambda device_id: asyncio.sleep(0))

    ws = FakeWebSocket(query_params={"patch_token": token})
    await agent_module.run_patches_websocket(ws, 5)

    assert ws._accepted is True
    assert ws.close_code is None or ws.close_code == 1000  # normal close
    joined = "\n".join(ws.sent)
    assert "Detected package manager: apt" in joined
    assert "Running full system upgrade" in joined
    assert "[Success] Updates completed successfully!" in joined
    assert "stdout line" in joined


@pytest.mark.asyncio
async def test_run_patches_websocket_security_only(monkeypatch):
    token = _seed_patch_token(device_id=5, mode="security-only")

    async def fake_probe(host_ip, ssh_user, ssh_password, ssh_key, ssh_port):
        return {"patch_manager": "apt", "packages": [], "error": None}

    captured = {}

    async def fake_run_stream(*, command, **kwargs):
        captured["command"] = command
        return True, "Success"

    monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", _auth_ok)
    monkeypatch.setattr(agent_module, "list_device_updates", fake_probe)
    monkeypatch.setattr(agent_module, "run_ssh_command_stream", fake_run_stream)
    monkeypatch.setattr(agent_module, "_clear_device_patch_state", lambda device_id: asyncio.sleep(0))

    ws = FakeWebSocket(query_params={"patch_token": token})
    await agent_module.run_patches_websocket(ws, 5)

    assert "install --only-upgrade" in captured["command"]
    joined = "\n".join(ws.sent)
    assert "Running security updates only" in joined


@pytest.mark.asyncio
async def test_run_patches_websocket_rejects_invalid_token(monkeypatch):
    monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", _auth_ok)

    ws = FakeWebSocket(query_params={"patch_token": "patch_tok_unknown"})
    await agent_module.run_patches_websocket(ws, 5)

    assert ws.close_code == 4001
    assert ws.close_reason == "Invalid session token"


@pytest.mark.asyncio
async def test_run_patches_websocket_unsupported_manager(monkeypatch):
    token = _seed_patch_token(device_id=5)

    async def fake_probe(host_ip, ssh_user, ssh_password, ssh_key, ssh_port):
        return {"patch_manager": "pacman", "packages": [], "error": None}

    monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", _auth_ok)
    monkeypatch.setattr(agent_module, "list_device_updates", fake_probe)

    ws = FakeWebSocket(query_params={"patch_token": token})
    await agent_module.run_patches_websocket(ws, 5)

    joined = "\n".join(ws.sent)
    assert "is not supported" in joined
    assert ws.close_code == 1000  # normal close after error message


@pytest.mark.asyncio
async def test_run_patches_websocket_probe_error(monkeypatch):
    token = _seed_patch_token(device_id=5)

    async def fake_probe(host_ip, ssh_user, ssh_password, ssh_key, ssh_port):
        return {"patch_manager": None, "error": "apt-get update failed (exit 100)."}

    monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", _auth_ok)
    monkeypatch.setattr(agent_module, "list_device_updates", fake_probe)

    ws = FakeWebSocket(query_params={"patch_token": token})
    await agent_module.run_patches_websocket(ws, 5)

    joined = "\n".join(ws.sent)
    assert "apt-get update failed" in joined
    assert ws.close_code == 1000


@pytest.mark.asyncio
async def test_run_patches_websocket_failed_stream(monkeypatch):
    token = _seed_patch_token(device_id=5)

    async def fake_probe(host_ip, ssh_user, ssh_password, ssh_key, ssh_port):
        return {"patch_manager": "dnf", "packages": [], "error": None}

    async def fake_run_stream(*, command, **kwargs):
        return False, "Command exited with code 1"

    monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", _auth_ok)
    monkeypatch.setattr(agent_module, "list_device_updates", fake_probe)
    monkeypatch.setattr(agent_module, "run_ssh_command_stream", fake_run_stream)

    ws = FakeWebSocket(query_params={"patch_token": token})
    await agent_module.run_patches_websocket(ws, 5)

    joined = "\n".join(ws.sent)
    assert "[Error] Update failed: Command exited with code 1" in joined
