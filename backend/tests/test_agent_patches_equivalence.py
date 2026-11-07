"""The patch-run WebSocket behaves as before the agent_patches refactor.

A frozen copy of run_patches_websocket as of 0.7.0-rc.7 runs next to the live one over
sessions (mode, user, password, key passphrase, pinned host key, strict mode), probe results
(apt/dnf/yum/unknown, warnings, refused sudo, no package manager, exceptions), host keys
learned during the probe or the run, stream outcomes, a client that leaves mid-run, and
probe/stream functions with narrow or **kwargs signatures. Everything sent, closed, audited,
passed to the SSH functions and persisted must match.
"""

import asyncio
import inspect
import itertools
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

import app.api.agent as agent_module
import app.api.agent_patches as ap


# --- frozen copy (0.7.0-rc.7) ---------------------------------------------------------

async def _old_run_patches_websocket(websocket, device_id):
    from app.api.auth import authenticate_websocket_authorized

    auth_info = await authenticate_websocket_authorized(
        websocket, endpoint_type="agent", device_id=device_id, allowed_levels=("session",),
    )
    if not auth_info:
        return
    await websocket.accept()
    session_data = await ap._consume_patch_session(websocket, device_id)
    if not session_data:
        await websocket.close(code=4001, reason="Invalid session token")
        return

    mode = session_data["mode"]
    host_ip = session_data["host_ip"]
    actor = ap.actor_from_identity(auth_info.get("identity"))
    ssh_user = session_data["ssh_user"]
    ssh_password = session_data["ssh_password"]
    ssh_key = session_data["ssh_key"]
    ssh_key_passphrase = session_data.get("ssh_key_passphrase")
    ssh_port = session_data["ssh_port"]
    pinned_host_key = session_data.get("pinned_host_key")
    tofu_policy = ap.TofuHostKeyPolicy() if pinned_host_key is None and not ap.settings.ssh_strict_mode else None

    await websocket.send_text("[Info] Starting update session...\r\n")
    await websocket.send_text("[Info] Detecting target system configuration...\r\n")

    probe_kwargs = dict(host_ip=host_ip, ssh_user=ssh_user, ssh_password=ssh_password, ssh_key=ssh_key, ssh_port=ssh_port)
    list_updates_fn = ap._get_agent_attr("list_device_updates", ap.list_device_updates)
    sig = inspect.signature(list_updates_fn)
    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if ("ssh_key_passphrase" in sig.parameters or accepts_var_kw) and ssh_key_passphrase is not None:
        probe_kwargs["ssh_key_passphrase"] = ssh_key_passphrase
    if ("pinned_host_key" in sig.parameters or accepts_var_kw) and pinned_host_key is not None:
        probe_kwargs["pinned_host_key"] = pinned_host_key
    if ("tofu_policy" in sig.parameters or accepts_var_kw) and tofu_policy is not None:
        probe_kwargs["tofu_policy"] = tofu_policy

    try:
        probe = await list_updates_fn(**probe_kwargs)
    except Exception as e:
        await ap.audit(websocket, "agent.patches", "failed", device_id=device_id, target=host_ip, detail=f"{mode}: SSH probe failed", actor=actor)
        await websocket.send_text(f"[Error] SSH probe failed: {e}\r\n")
        await websocket.close()
        return

    pkg_manager = probe.get("patch_manager")
    probe_error = probe.get("error")
    if probe_error and (probe.get("sudo_rejected") or not pkg_manager):
        await ap.audit(websocket, "agent.patches", "failed", device_id=device_id, target=host_ip, detail=f"{mode}: {probe_error}", actor=actor)
        await websocket.send_text(f"[Error] {probe_error}\r\n")
        await websocket.close()
        return
    if probe_error:
        await websocket.send_text(f"[Warn] {probe_error}\r\n")
    if not pkg_manager:
        detected_os = probe.get("detected_os")
        detail = detected_os or "no recognizable package manager found"
        await websocket.send_text("[Error] Unsupported package manager or system type.\r\n")
        await websocket.send_text(f"[Info] Target system reports: {detail}\r\n")
        await websocket.close()
        return

    if tofu_policy and tofu_policy.captured:
        async with ap.async_session() as db:
            await ap._persist_captured_host_key(db, host_ip, ssh_port, tofu_policy.captured)
            pinned_host_key = ap.PinnedHostKey(key_type=tofu_policy.captured.key_type, fingerprint=tofu_policy.captured.fingerprint)
            tofu_policy = None

    await websocket.send_text(f"[Info] Detected package manager: {pkg_manager}\r\n")
    cmd = ap._build_update_command(pkg_manager, mode)
    if cmd is None:
        await websocket.send_text(f"[Error] Package manager {pkg_manager} is not supported.\r\n")
        await websocket.close()
        return
    if mode == "security-only":
        await websocket.send_text("[Info] Running security updates only...\r\n")
    else:
        await websocket.send_text("[Info] Running full system upgrade...\r\n")

    client_connected = True

    async def stream_callback(data):
        nonlocal client_connected
        if client_connected:
            cleaned = data.replace("\r\n", "\n").replace("\n", "\r\n")
            client_connected = await ap._send_ws_text(websocket, cleaned)

    stream_kwargs = dict(host_ip=host_ip, ssh_user=ssh_user, ssh_password=ssh_password, ssh_key=ssh_key,
                         ssh_port=ssh_port, command=cmd, output_callback=stream_callback)
    stream_fn = ap._get_agent_attr("run_ssh_command_stream", ap.run_ssh_command_stream)
    stream_sig = inspect.signature(stream_fn)
    stream_accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in stream_sig.parameters.values())
    if ("ssh_key_passphrase" in stream_sig.parameters or stream_accepts_var_kw) and ssh_key_passphrase is not None:
        stream_kwargs["ssh_key_passphrase"] = ssh_key_passphrase
    if ("pinned_host_key" in stream_sig.parameters or stream_accepts_var_kw) and pinned_host_key is not None:
        stream_kwargs["pinned_host_key"] = pinned_host_key
    if ("tofu_policy" in stream_sig.parameters or stream_accepts_var_kw) and tofu_policy is not None:
        stream_kwargs["tofu_policy"] = tofu_policy

    success, msg = await stream_fn(**stream_kwargs)
    await ap.audit(websocket, "agent.patches", "ok" if success else "failed", device_id=device_id, target=host_ip, detail=mode, actor=actor)
    if success and tofu_policy and tofu_policy.captured:
        async with ap.async_session() as db:
            await ap._persist_captured_host_key(db, host_ip, ssh_port, tofu_policy.captured)
    if success:
        clear_fn = ap._get_agent_attr("_clear_device_patch_state", ap._clear_device_patch_state)
        await clear_fn(device_id)
    if not client_connected:
        return
    if success:
        await ap._send_ws_text(websocket, "\r\n[Success] Updates completed successfully!\r\n")
    else:
        await ap._send_ws_text(websocket, f"\r\n[Error] Update failed: {msg}\r\n")
    try:
        await websocket.close()
    except (RuntimeError, OSError):
        pass


# --- doubles ------------------------------------------------------------------------------

class FakeWebSocket:
    def __init__(self, token, disconnect_after=None):
        self.query_params = {"patch_token": token} if token else {}
        self.events = []
        self.disconnect_after = disconnect_after

    async def accept(self):
        self.events.append(("accept",))

    async def send_text(self, text):
        sends = sum(1 for e in self.events if e[0] == "send")
        if self.disconnect_after is not None and sends >= self.disconnect_after:
            raise WebSocketDisconnect(code=1001)
        self.events.append(("send", text))

    async def close(self, code=1000, reason=None):
        self.events.append(("close", code, reason))


class FakeTofu:
    def __init__(self):
        self.captured = None


CAPTURED = SimpleNamespace(key_type="ssh-ed25519", fingerprint="SHA256:abc", public_key="AAAA")
PINNED = ap.PinnedHostKey(key_type="ssh-rsa", fingerprint="SHA256:pinned")


def _describe(kwargs):
    """Comparable view of the kwargs handed to the SSH functions."""
    out = {}
    for key, value in kwargs.items():
        if key == "output_callback":
            continue
        if key == "tofu_policy":
            out[key] = type(value).__name__
        elif key == "pinned_host_key":
            out[key] = (value.key_type, value.fingerprint)
        else:
            out[key] = value
    return out


def _probe_fn(record, result, narrow, capture):
    async def body(kwargs):
        record.append(("probe", _describe(kwargs)))
        if capture and kwargs.get("tofu_policy") is not None:
            kwargs["tofu_policy"].captured = CAPTURED
        if isinstance(result, Exception):
            raise result
        return dict(result)

    if narrow:
        async def probe(host_ip, ssh_user, ssh_password, ssh_key, ssh_port):
            return await body(dict(host_ip=host_ip, ssh_user=ssh_user, ssh_password=ssh_password, ssh_key=ssh_key, ssh_port=ssh_port))
    else:
        async def probe(**kwargs):
            return await body(kwargs)
    return probe


def _stream_fn(record, outcome, narrow, capture):
    async def body(kwargs):
        record.append(("stream", _describe(kwargs)))
        if capture and kwargs.get("tofu_policy") is not None:
            kwargs["tofu_policy"].captured = CAPTURED
        for chunk in ("line one\n", "line two\r\nline three\n", "tail"):
            await kwargs["output_callback"](chunk)
        return outcome

    if narrow:
        async def stream(*, host_ip, ssh_user, ssh_password, ssh_key, ssh_port, command, output_callback):
            return await body(dict(host_ip=host_ip, ssh_user=ssh_user, ssh_password=ssh_password, ssh_key=ssh_key,
                                   ssh_port=ssh_port, command=command, output_callback=output_callback))
    else:
        async def stream(**kwargs):
            return await body(kwargs)
    return stream


SESSIONS = [
    dict(mode="full", ssh_user="root", ssh_password=None, ssh_key=None, pinned_host_key=None, passphrase=None),
    dict(mode="security-only", ssh_user="oliver", ssh_password="pw", ssh_key="KEY", pinned_host_key=None, passphrase="pp"),
    dict(mode="full", ssh_user="oliver", ssh_password=None, ssh_key="KEY", pinned_host_key=PINNED, passphrase=None),
]
PROBES = [
    {"patch_manager": "apt", "packages": [], "error": None},
    {"patch_manager": "dnf", "packages": []},
    {"patch_manager": "yum", "packages": []},
    {"patch_manager": "pacman", "packages": []},
    {"patch_manager": "apt", "error": "apt-get update failed (exit 100)."},
    {"patch_manager": "apt", "error": "Sudo password rejected", "sudo_rejected": True},
    {"patch_manager": None, "error": "connection refused"},
    {"patch_manager": None, "detected_os": "ID=alpine"},
    {"patch_manager": None},
    OSError("timed out"),
]
STREAMS = [(True, "Success"), (False, "Command exited with code 100")]


async def _run(fn, monkeypatch, session, probe, stream, strict, narrow, capture_at, disconnect_after):
    record = []
    token = "patch_tok_equivalence"
    ap._temp_patch_tokens.clear()
    ap._temp_patch_tokens[token] = {
        "device_id": 5, "host_ip": "192.0.2.50", "ssh_user": session["ssh_user"], "ssh_password": session["ssh_password"],
        "ssh_key": session["ssh_key"], "ssh_port": 2222, "mode": session["mode"], "created_at": time.time(),
        "ssh_key_passphrase": session["passphrase"], "pinned_host_key": session["pinned_host_key"],
    }

    async def auth_ok(websocket, endpoint_type, device_id=None, allowed_levels=()):
        return {"authenticated": True, "auth_type": "session", "identity": "session"}

    async def fake_audit(websocket, action, result, **kw):
        record.append(("audit", action, result, kw))

    async def fake_persist(_db, host, port, captured):
        record.append(("persist", host, port, captured.fingerprint))

    @asynccontextmanager
    async def fake_session():
        yield None

    async def fake_clear(device_id):
        record.append(("clear", device_id))

    monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", auth_ok)
    monkeypatch.setattr(ap, "audit", fake_audit)
    monkeypatch.setattr(ap, "_persist_captured_host_key", fake_persist)
    monkeypatch.setattr(ap, "async_session", fake_session)
    monkeypatch.setattr(ap, "TofuHostKeyPolicy", FakeTofu)
    monkeypatch.setattr(ap.settings, "ssh_strict_mode", strict)
    monkeypatch.setattr(agent_module, "list_device_updates", _probe_fn(record, probe, narrow, capture_at == "probe"))
    monkeypatch.setattr(agent_module, "run_ssh_command_stream", _stream_fn(record, stream, narrow, capture_at == "stream"))
    monkeypatch.setattr(agent_module, "_clear_device_patch_state", fake_clear)

    ws = FakeWebSocket(token, disconnect_after)
    await fn(ws, 5)
    return ws.events, record


@pytest.mark.asyncio
async def test_patch_run_matches_for_every_scenario(monkeypatch):
    diffs, count = [], 0
    for session, probe, stream, strict, narrow, capture_at, disconnect_after in itertools.product(
        SESSIONS, PROBES, STREAMS, (False, True), (False, True), (None, "probe", "stream"), (None, 7)
    ):
        args = (session, probe, stream, strict, narrow, capture_at, disconnect_after)
        before = await _run(_old_run_patches_websocket, monkeypatch, *args)
        now = await _run(ap.run_patches_websocket, monkeypatch, *args)
        count += 1
        if before != now:
            diffs.append((args, before, now))
    assert count == 3 * 10 * 2 * 2 * 2 * 3 * 2
    assert diffs[:2] == []


@pytest.mark.asyncio
async def test_patch_run_matches_without_auth_or_with_a_bad_token(monkeypatch):
    async def auth_refused(websocket, endpoint_type, device_id=None, allowed_levels=()):
        return None

    for fn in (_old_run_patches_websocket, ap.run_patches_websocket):
        monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", auth_refused)
        ws = FakeWebSocket("anything")
        await fn(ws, 5)
        assert ws.events == []

    results = []
    for fn in (_old_run_patches_websocket, ap.run_patches_websocket):
        async def auth_ok(websocket, endpoint_type, device_id=None, allowed_levels=()):
            return {"authenticated": True, "auth_type": "session", "identity": "session"}

        monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", auth_ok)
        ap._temp_patch_tokens.clear()
        ws = FakeWebSocket("unknown-token")
        await fn(ws, 5)
        results.append(ws.events)
    assert results[0] == results[1]
    assert results[0][-1] == ("close", 4001, "Invalid session token")
