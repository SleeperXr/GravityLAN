"""The helpers run_patches_websocket is built from (app/api/agent_patches.py): SSH options from a
patch session, pinning a host key learned during the probe, announcing the update command and
streaming the update."""

import pytest

import app.api.agent_patches as ap
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
    await ap._stream_update(Socket(), 7, "full", "admin", ssh, {"tofu_policy": policy}, "dnf upgrade -y")

    assert calls["audit"] == [("agent.patches", "ok" if success else "failed", "192.0.2.10", "full")]
    assert calls["cleared"] == ([7] if success else [])
    assert calls["remembered"] == ([CAPTURED] if success else [])
    assert calls["reported"] == [(success, "done" if success else "failed")]
