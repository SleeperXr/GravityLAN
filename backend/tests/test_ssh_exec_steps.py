"""The steps _exec_impl is built from (app/services/ssh_utils.py): answering sudo's password
prompt and turning an exit code plus stderr into output or a readable error."""

from types import SimpleNamespace

import pytest

import app.services.ssh_utils as su


class Stdin:
    def __init__(self, fail_shutdown=False):
        self.written, self.flushed = [], False
        self.channel = SimpleNamespace(shutdown_write=self._shutdown)
        self.fail_shutdown, self.shut = fail_shutdown, False

    def write(self, text):
        self.written.append(text)

    def flush(self):
        self.flushed = True

    def _shutdown(self):
        if self.fail_shutdown:
            raise OSError("already closed")
        self.shut = True


def test_sudo_password_only_for_sudo_dash_s():
    stdin = Stdin()
    su._feed_sudo_password(stdin, "sudo -n true", "pw")
    su._feed_sudo_password(stdin, "sudo -S true", None)
    assert stdin.written == []

    su._feed_sudo_password(stdin, "sudo -S true", "pw")
    assert (stdin.written, stdin.flushed, stdin.shut) == (["pw\n"], True, True)


def test_a_failing_stdin_shutdown_is_ignored():
    stdin = Stdin(fail_shutdown=True)
    su._feed_sudo_password(stdin, "sudo -S true", "pw")
    assert stdin.written == ["pw\n"]


@pytest.mark.parametrize("err", ["rm: cannot remove: not found", "No such file or directory"])
def test_exit_1_with_a_missing_file_still_returns_the_output(err):
    assert su._check_exit(1, "partial", err) == "partial"


def test_success_returns_the_output():
    assert su._check_exit(0, "ok", "warning on stderr") == "ok"


def test_other_failures_name_the_last_error_line():
    with pytest.raises(su.RemoteCommandError, match=r"failed \(exit 2\): second line\.$"):
        su._check_exit(2, "", "first line\nsecond line")
    with pytest.raises(su.RemoteCommandError, match=r"failed \(exit 3\)\.$"):
        su._check_exit(3, "", "")


@pytest.mark.parametrize("phrase", ["incorrect password", "falsches passwort", "nicht funktioniert", "fehlversuch"])
def test_detects_sudo_password_rejected(phrase):
    with pytest.raises(su.SudoPasswordError, match="Sudo password rejected"):
        su._check_exit(1, "", f"sudo: {phrase}")


def test_wait_for_exit_waits_until_channel_ready(monkeypatch):
    states = [False, True]
    channel = SimpleNamespace(exit_status_ready=lambda: states.pop(0), close=lambda: None)
    stdout = SimpleNamespace(channel=channel)
    slept = []
    monkeypatch.setattr(su.time, "sleep", lambda s: slept.append(s))
    su._wait_for_exit(stdout, "true", timeout=5)
    assert slept == [0.1]


def test_build_connect_kwargs_invalid_key():
    kwargs, err = su.build_connect_kwargs("1.2.3.4", "user", 22, None, "NOT A VALID KEY")
    assert kwargs == {}
    assert err == "Invalid SSH key format or encrypted key."


def test_build_connect_kwargs_missing_credentials():
    kwargs, err = su.build_connect_kwargs("1.2.3.4", "user", 22, None, None)
    assert kwargs == {}
    assert err == "Neither password nor SSH key provided."


def test_connect_with_gateway_fallback_direct_success():
    from unittest.mock import MagicMock
    client = MagicMock()
    su.connect_with_gateway_fallback(client, {"hostname": "1.2.3.4"}, "1.2.3.4")
    client.connect.assert_called_once_with(hostname="1.2.3.4")


def test_remote_runner_run_batch():
    from unittest.mock import MagicMock
    runner = su.RemoteRunner(MagicMock(), has_sudo=False, ssh_user="root", ssh_password=None)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(runner, "run", lambda cmd, timeout=15: f"out:{cmd}")
        assert runner.run_batch(["c1", "c2"]) == ["out:c1", "out:c2"]
