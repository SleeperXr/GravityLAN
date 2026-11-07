"""A failed agent deploy says why: sudo without a password, a hanging command, an unreachable host,
never the command text (staged files carry the agent token) and never just "unexpected internal error"."""

from types import SimpleNamespace

import pytest

import app.services.agent_deployer as dep
from app.services import ssh_utils
from app.services.ssh_utils import RemoteCommandError, RemoteTimeoutError, SudoPasswordError


class Channel:
    def __init__(self, code, ready=True):
        self.code, self.ready = code, ready

    def exit_status_ready(self):
        return self.ready

    def recv_exit_status(self):
        return self.code

    def close(self):
        pass

    def shutdown_write(self):
        pass


def _client(code=0, out="", err="", ready=True):
    channel = Channel(code, ready)
    stream = lambda text: SimpleNamespace(read=lambda: text.encode(), channel=channel)  # noqa: E731
    stdin = SimpleNamespace(write=lambda _s: None, flush=lambda: None, channel=channel)
    return SimpleNamespace(exec_command=lambda cmd, timeout=None: (stdin, stream(out), stream(err)))


SECRET_CMD = "sudo -n -- sh -c 'cat > /tmp/x << EOF\n{\"token\": \"secret-token\"}\nEOF'"


@pytest.mark.parametrize("err", ["sudo: a password is required", "sudo: Ein Passwort ist notwendig", "sudo: Passwort erforderlich"])
def test_sudo_without_password_names_the_cause(err):
    with pytest.raises(SudoPasswordError, match="sudo needs a password"):
        ssh_utils._exec_impl(_client(1, err=err), SECRET_CMD, 5, None)


def test_a_failed_command_does_not_show_the_command():
    with pytest.raises(RemoteCommandError) as caught:
        ssh_utils._exec_impl(_client(2, err="mkdir: cannot create directory '/opt/x': Read-only file system"), SECRET_CMD, 5, None)
    assert "Read-only file system" in str(caught.value)
    assert "secret-token" not in str(caught.value)


def test_a_hanging_sudo_says_it_may_wait_for_a_password(monkeypatch):
    # The first reading starts the wait, every later one (logging reads the clock too) is past the timeout
    clock = iter([0])
    monkeypatch.setattr(ssh_utils.time, "time", lambda: next(clock, 100))
    monkeypatch.setattr(ssh_utils.time, "sleep", lambda _s: None)
    with pytest.raises(RemoteTimeoutError) as caught:
        ssh_utils._exec_impl(_client(ready=False), SECRET_CMD, 15, None)
    assert "within 15s" in str(caught.value) and "password" in str(caught.value)
    assert "secret-token" not in str(caught.value)


def test_deploy_errors_reach_the_user():
    msg = "sudo needs a password for this user. Enter the user's password; it is used for sudo and not stored."
    assert dep._map_ssh_error(SudoPasswordError(msg), "192.0.2.5") == (False, msg)
    ok, text = dep._map_ssh_error(TimeoutError("timed out"), "192.0.2.5")
    assert ok is False and "192.0.2.5" in text and "TimeoutError" in text
    # A missing local file is no network problem: still the internal error
    assert dep._map_ssh_error(FileNotFoundError("agent.py"), "192.0.2.5") is None
    assert dep._map_ssh_error(RuntimeError("other"), "192.0.2.5") is None


def test_saved_key_without_sudo_password_fails_with_the_reason(monkeypatch):
    """The whole deploy path: sudo refuses, the result names sudo instead of an internal error."""

    class Client:
        def get_transport(self):
            return None

        def close(self):
            pass

    monkeypatch.setattr(dep, "_client_for", lambda *a: Client())
    monkeypatch.setattr(dep, "build_connect_kwargs", lambda *a: ({}, None))
    monkeypatch.setattr(dep, "connect_with_gateway_fallback", lambda *a: None)
    monkeypatch.setattr(dep, "_check_sudo", lambda c: True)
    monkeypatch.setattr(dep, "_stage_file", lambda *a: None)
    monkeypatch.setattr(dep, "_verify_remote_sha256", lambda *a: True)
    monkeypatch.setattr(dep, "_probe_platform", lambda *a: (True, False))

    def refuse(self, commands, timeout=15):
        raise SudoPasswordError("sudo needs a password for this user.")

    monkeypatch.setattr(ssh_utils.RemoteRunner, "run_sudo_batch", refuse)
    ok, message, token = dep._deploy_agent_blocking(
        host_ip="192.0.2.5", ssh_user="sleeper", ssh_password=None, ssh_key="KEY", ssh_port=22,
        server_url="http://srv", device_id=1,
    )
    assert (ok, message, token) == (False, "sudo needs a password for this user.", "")
