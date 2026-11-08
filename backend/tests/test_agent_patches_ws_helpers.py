"""The helpers run_patches_websocket is built from (app/api/agent_patches.py): SSH options from a
patch session, pinning a host key learned during the probe, announcing the update command and
streaming the update."""

import app.api.agent_patches as ap
import pytest
from app.services.ssh_utils import CapturedHostKey, PinnedHostKey, TofuHostKeyPolicy

SESSION = {
    "host_ip": "192.0.2.10", "ssh_user": "admin", "ssh_password": "pw", "ssh_key": None, "ssh_port": 22,
    "ssh_key_passphrase": None, "mode": "full",
}
CAPTURED = CapturedHostKey(key_type="ssh-ed25519", fingerprint="SHA256:abc", public_key="ssh-ed25519 AAAA")


class Socket:
    def __init__(self):
        self.lines, self.closed = [], False

    async def send_text(self, text):
        self.lines.append(text)

    async def close(self, *a, **k):
        self.closed = True


def test_session_options_learn_the_key_unless_pinned_or_strict(monkeypatch):
    monkeypatch.setattr(ap.settings, "ssh_strict_mode", False)
    ssh, optional = ap._session_ssh_options(SESSION)
    assert ssh == {k: SESSION[k] for k in ("host_ip", "ssh_user", "ssh_password", "ssh_key", "ssh_port")}
    assert isinstance(optional["tofu_policy"], TofuHostKeyPolicy) and optional["pinned_host_key"] is None

    pinned = PinnedHostKey(key_type="ssh-ed25519", fingerprint="SHA256:abc")
    _, optional = ap._session_ssh_options({**SESSION, "pinned_host_key": pinned})
    assert optional["tofu_policy"] is None and optional["pinned_host_key"] is pinned

    monkeypatch.setattr(ap.settings, "ssh_strict_mode", True)
    _, optional = ap._session_ssh_options(SESSION)
    assert optional["tofu_policy"] is None


async def test_a_key_learned_in_the_probe_is_stored_and_pinned(monkeypatch):
    remembered = []

    async def remember(host, port, captured):
        remembered.append((host, port, captured))

    monkeypatch.setattr(ap, "_remember_host_key", remember)
    policy = TofuHostKeyPolicy()
    policy.captured = CAPTURED
    optional = {"tofu_policy": policy, "pinned_host_key": None}

    await ap._pin_probed_host_key({"host_ip": "192.0.2.10", "ssh_port": 22}, optional)

    assert remembered == [("192.0.2.10", 22, CAPTURED)]
    assert optional == {"tofu_policy": None, "pinned_host_key": PinnedHostKey(key_type="ssh-ed25519", fingerprint="SHA256:abc")}


async def test_nothing_to_pin_without_a_learned_key(monkeypatch):
    monkeypatch.setattr(ap, "_remember_host_key", None)  # would fail if called
    optional = {"tofu_policy": TofuHostKeyPolicy(), "pinned_host_key": None}
    await ap._pin_probed_host_key({"host_ip": "192.0.2.10", "ssh_port": 22}, optional)
    assert optional["pinned_host_key"] is None


@pytest.mark.parametrize("mode, announcement", [("security-only", "security updates only"), ("full", "full system upgrade")])
async def test_update_command_is_announced(mode, announcement):
    ws = Socket()
    cmd = await ap._announce_update_command(ws, "dnf", mode)
    assert cmd == ("dnf upgrade --security -y" if mode == "security-only" else "dnf upgrade -y")
    assert ws.lines[0] == "[Info] Detected package manager: dnf\r\n"
    assert announcement in ws.lines[1]
    assert not ws.closed


async def test_unsupported_package_manager_closes_the_session():
    ws = Socket()
    assert await ap._announce_update_command(ws, "pacman", "full") is None
    assert ws.lines[-1] == "[Error] Package manager pacman is not supported.\r\n"
    assert ws.closed


@pytest.mark.parametrize("success", [True, False])
async def test_stream_update_audits_and_clears_only_on_success(monkeypatch, success):
    calls = {"audit": [], "cleared": [], "remembered": [], "reported": []}

    async def stream(**kwargs):
        await kwargs["output_callback"]("line\n")
        return success, "done" if success else "failed"

    async def audit(ws, action, result, **kw):
        calls["audit"].append((action, result, kw["target"], kw["detail"]))

    async def clear(device_id):
        calls["cleared"].append(device_id)

    async def remember(host, port, captured):
        calls["remembered"].append(captured)

    async def report(ws, ok, msg):
        calls["reported"].append((ok, msg))

    class Sink:
        connected = True

        def __init__(self, ws, device_id):
            pass

        async def __call__(self, line):
            pass

    attrs = {"run_ssh_command_stream": stream, "_clear_device_patch_state": clear}
    monkeypatch.setattr(ap, "_ClientSink", Sink)
    monkeypatch.setattr(ap, "_get_agent_attr", lambda name, default: attrs[name])
    monkeypatch.setattr(ap, "_ssh_kwargs_for", lambda fn, base, **optional: base)
    monkeypatch.setattr(ap, "audit", audit)
    monkeypatch.setattr(ap, "_remember_host_key", remember)
    monkeypatch.setattr(ap, "_report_result", report)
    policy = TofuHostKeyPolicy()
    policy.captured = CAPTURED

    ssh = {"host_ip": "192.0.2.10", "ssh_port": 22}
    params = ap.PatchStreamParams(
        websocket=Socket(),
        device_id=7,
        mode="full",
        actor="admin",
        ssh=ssh,
        optional={"tofu_policy": policy},
        cmd="dnf upgrade -y",
    )
    await ap._stream_update(params)

    assert calls["audit"] == [("agent.patches", "ok" if success else "failed", "192.0.2.10", "full")]
    assert calls["cleared"] == ([7] if success else [])
    assert calls["remembered"] == ([CAPTURED] if success else [])
    assert calls["reported"] == [(success, "done" if success else "failed")]


# --- Additional tests: error handling, missing paths, and endpoint coverage ---

import time
from unittest.mock import MagicMock

from app.models.device import Device
from app.schemas.agent import AgentDeployRequest, PatchActionRequest
from app.services.ssh_credentials import StoredLoginError
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError


def test_get_agent_attr_fallback():
    assert ap._get_agent_attr("nonexistent_attribute_xyz", "fallback_value") == "fallback_value"


@pytest.mark.asyncio
async def test_persist_captured_host_key(db):
    await ap._persist_captured_host_key(db, "192.0.2.99", 22, CAPTURED)
    # Re-running with existing entry is an idempotent no-op
    await ap._persist_captured_host_key(db, "192.0.2.99", 22, CAPTURED)


@pytest.mark.asyncio
async def test_push_metrics_to_subscribers_handles_disconnect(monkeypatch):
    class BrokenWs:
        async def send_json(self, data):
            raise OSError("connection reset")

    monkeypatch.setattr(ap, "_ws_subscribers", {10: [BrokenWs()]})
    monkeypatch.setattr(ap, "_latest_metrics", {10: {"cpu": 50}})
    await ap._push_metrics_to_subscribers(10)


@pytest.mark.asyncio
async def test_report_result_handles_close_error():
    class BrokenCloseSocket:
        def __init__(self):
            self.lines = []

        async def send_text(self, text):
            self.lines.append(text)

        async def close(self):
            raise OSError("already closed")

    ws = BrokenCloseSocket()
    await ap._report_result(ws, False, "crash")
    assert any("crash" in line for line in ws.lines)


@pytest.mark.asyncio
async def test_clear_device_patch_state_sqlalchemy_error(monkeypatch):
    class FailingSession:
        async def execute(self, *a, **k):
            raise SQLAlchemyError("database locked")

        async def commit(self):
            pass

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield FailingSession()

    monkeypatch.setattr(ap, "async_session", fake_session)
    await ap._clear_device_patch_state(1)


@pytest.mark.asyncio
async def test_clear_device_patch_state_no_metrics(monkeypatch):
    class FakeScalars:
        def first(self):
            return None

    class FakeResult:
        def scalars(self):
            return FakeScalars()

    class FakeSession:
        async def execute(self, *a, **k):
            return FakeResult()

        async def commit(self):
            pass

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield FakeSession()

    monkeypatch.setattr(ap, "async_session", fake_session)
    await ap._clear_device_patch_state(99999)


@pytest.mark.asyncio
async def test_query_device_patches_missing_device(db):
    request = AgentDeployRequest(ssh_user="root")
    http_req = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await ap.query_device_patches(9999, request, http_req, db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_query_device_patches_success_and_error(db, monkeypatch):
    device = Device(ip="192.0.2.15", display_name="Test Host")
    db.add(device)
    await db.commit()
    await db.refresh(device)

    request = AgentDeployRequest(ssh_user="root", ssh_password="pw")
    http_req = MagicMock()

    async def mock_list_updates(**kwargs):
        return {
            "patch_manager": "apt",
            "packages": [
                {"package": "openssl", "current_version": "1.1", "new_version": "1.2", "repo": "main"}
            ],
            "major_upgrade_available": None,
        }

    monkeypatch.setattr(ap, "list_device_updates", mock_list_updates)
    monkeypatch.setattr(ap, "_get_agent_attr", lambda name, default: mock_list_updates)

    resp = await ap.query_device_patches(device.id, request, http_req, db)
    assert resp.device_id == device.id
    assert resp.patch_manager == "apt"
    assert len(resp.packages) == 1
    assert resp.packages[0].package == "openssl"

    async def mock_list_updates_err(**kwargs):
        return {"error": "SSH connection failed"}

    monkeypatch.setattr(ap, "_get_agent_attr", lambda name, default: mock_list_updates_err)
    with pytest.raises(HTTPException) as exc:
        await ap.query_device_patches(device.id, request, http_req, db)
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_resolve_patch_credentials_missing_browser_session(db):
    device = Device(ip="192.0.2.20", display_name="Node 20")
    db.add(device)
    await db.commit()
    await db.refresh(device)

    http_req = MagicMock()
    http_req.cookies = {}

    req_profile = PatchActionRequest(mode="upgrade", ssh_user="root", profile_id=1)
    with pytest.raises(HTTPException) as exc:
        await ap._resolve_patch_credentials(db, device, req_profile, http_req)
    assert exc.value.status_code == 403

    req_key = PatchActionRequest(mode="upgrade", ssh_user="root", key_id=1)
    with pytest.raises(HTTPException) as exc:
        await ap._resolve_patch_credentials(db, device, req_key, http_req)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_resolve_patch_credentials_stored_login_error(db, monkeypatch):
    device = Device(ip="192.0.2.30", display_name="Node 30")
    db.add(device)
    await db.commit()
    await db.refresh(device)

    http_req = MagicMock()
    monkeypatch.setattr(ap, "has_browser_session", lambda r: True)

    async def mock_resolve_key(*a, **kw):
        raise StoredLoginError("Key not found", 404)

    monkeypatch.setattr(ap, "resolve_stored_key", mock_resolve_key)
    req = PatchActionRequest(mode="upgrade", ssh_user="root", key_id=123)
    with pytest.raises(HTTPException) as exc:
        await ap._resolve_patch_credentials(db, device, req, http_req)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_prepare_patch_action_device_not_found(db):
    http_req = MagicMock()
    req = PatchActionRequest(mode="upgrade", ssh_user="root")
    with pytest.raises(HTTPException) as exc:
        await ap.prepare_patch_action(99999, req, http_req, db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_prepare_patch_action_expired_tokens_cleanup(db):
    device = Device(ip="192.0.2.25", display_name="Node 25")
    db.add(device)
    await db.commit()
    await db.refresh(device)

    ap._temp_patch_tokens["expired_tok"] = {
        "created_at": time.time() - 100,
        "device_id": device.id,
    }

    http_req = MagicMock()
    req = PatchActionRequest(mode="upgrade", ssh_user="root", ssh_password="pw")
    res = await ap.prepare_patch_action(device.id, req, http_req, db)
    assert "patch_token" in res
    assert "expired_tok" not in ap._temp_patch_tokens


@pytest.mark.asyncio
async def test_resolve_patch_credentials_with_profile(db, monkeypatch):
    device = Device(ip="192.0.2.35", display_name="Node 35")
    db.add(device)
    await db.commit()
    await db.refresh(device)

    http_req = MagicMock()
    monkeypatch.setattr(ap, "has_browser_session", lambda r: True)

    class MockLogin:
        host = "192.0.2.35"
        port = 22
        username = "admin"
        private_key = "KEY"
        passphrase = "PASS"
        pinned = None

    async def mock_profile(*a, **kw):
        return MockLogin()

    monkeypatch.setattr(ap, "resolve_key_profile", mock_profile)
    req = PatchActionRequest(mode="upgrade", profile_id=1, ssh_user="root")
    creds = await ap._resolve_patch_credentials(db, device, req, http_req)
    assert creds[0] == "192.0.2.35"
    assert creds[2] == "admin"

    async def mock_profile_err(*a, **kw):
        raise StoredLoginError("Profile error", 400)

    monkeypatch.setattr(ap, "resolve_key_profile", mock_profile_err)
    with pytest.raises(HTTPException) as exc:
        await ap._resolve_patch_credentials(db, device, req, http_req)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_query_device_patches_tofu_persisted(db, monkeypatch):
    device = Device(ip="192.0.2.50", display_name="Host 50")
    db.add(device)
    await db.commit()
    await db.refresh(device)

    request = AgentDeployRequest(ssh_user="root", ssh_password="pw")
    http_req = MagicMock()

    class FakeTofu:
        captured = CAPTURED

    monkeypatch.setattr(ap, "TofuHostKeyPolicy", FakeTofu)

    async def mock_list_updates(**kwargs):
        return {
            "patch_manager": "apt",
            "packages": [],
            "major_upgrade_available": None,
        }

    monkeypatch.setattr(ap, "_get_agent_attr", lambda name, default: mock_list_updates)
    resp = await ap.query_device_patches(device.id, request, http_req, db)
    assert resp.device_id == device.id
    assert resp.patch_manager == "apt"


@pytest.mark.asyncio
async def test_clear_device_patch_state_success(monkeypatch):
    class FakeMetric:
        patch_available = 5
        patch_security = 2

    fake_metric = FakeMetric()

    class FakeScalars:
        def first(self):
            return fake_metric

    class FakeResult:
        def scalars(self):
            return FakeScalars()

    class FakeSession:
        async def execute(self, *a, **k):
            return FakeResult()

        async def commit(self):
            pass

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        yield FakeSession()

    monkeypatch.setattr(ap, "async_session", fake_session)

    pushed = []

    class FakeWs:
        async def send_json(self, data):
            pushed.append(data)

    monkeypatch.setattr(ap, "_latest_metrics", {55: {"patch_available": 5, "patch_security": 2}})
    monkeypatch.setattr(ap, "_ws_subscribers", {55: [FakeWs()]})

    await ap._clear_device_patch_state(55)

    assert fake_metric.patch_available == 0
    assert fake_metric.patch_security == 0
    assert ap._latest_metrics[55]["patch_available"] == 0
    assert ap._latest_metrics[55]["patch_security"] == 0
    assert len(pushed) == 1
    assert pushed[0]["data"]["patch_available"] == 0



@pytest.mark.asyncio
async def test_push_metrics_to_subscribers_not_subscribed():
    await ap._push_metrics_to_subscribers(8888)

@pytest.mark.asyncio
async def test_resolve_patch_credentials_stored_key_success(db, monkeypatch):
    device = Device(ip="192.0.2.32", display_name="Node 32")
    db.add(device)
    await db.commit()
    await db.refresh(device)

    http_req = MagicMock()
    monkeypatch.setattr(ap, "has_browser_session", lambda r: True)

    async def mock_resolve_key(*a, **kw):
        return ("KEY_DATA", "PASSPHRASE")

    monkeypatch.setattr(ap, "resolve_stored_key", mock_resolve_key)
    req = PatchActionRequest(mode="upgrade", ssh_user="root", key_id=456)
    creds = await ap._resolve_patch_credentials(db, device, req, http_req)
    assert creds[4] == "KEY_DATA"
    assert creds[5] == "PASSPHRASE"
