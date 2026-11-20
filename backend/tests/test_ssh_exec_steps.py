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


@pytest.mark.parametrize("err", [
    "rm: cannot remove: not found",
    "No such file or directory",
    "wget: server returned error: HTTP/1.1 404 Not Found",
    "Not Found",
])
def test_exit_1_always_raises_remote_command_error(err):
    with pytest.raises(su.RemoteCommandError, match=r"failed \(exit 1\)"):
        su._check_exit(1, "partial", err)


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


def test_build_connect_kwargs_with_a_password():
    kwargs, err = su.build_connect_kwargs("1.2.3.4", "user", 2222, "pw", None)
    assert err is None
    assert kwargs == {"hostname": "1.2.3.4", "port": 2222, "username": "user", "timeout": 15, "password": "pw"}


def test_build_connect_kwargs_prefers_the_key_over_the_password(monkeypatch):
    key, loaded = object(), []
    monkeypatch.setattr(su, "_load_ssh_key", lambda text, passphrase: loaded.append((text, passphrase)) or key)
    kwargs, err = su.build_connect_kwargs("1.2.3.4", "user", 22, "pw", "KEY TEXT", "phrase")
    assert err is None
    assert kwargs["pkey"] is key and "password" not in kwargs
    assert loaded == [("KEY TEXT", "phrase")]


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


# --- Non-blocking stream drain, bounded memory and timeout tests ----------------


class MockDrainChannel:
    def __init__(
        self,
        stdout_chunks=None,
        stderr_chunks=None,
        exit_code=0,
        ready_after=0,
        never_ready=False,
    ):
        self.stdout_chunks = list(stdout_chunks or [])
        self.stderr_chunks = list(stderr_chunks or [])
        self.exit_code = exit_code
        self.ready_after = ready_after
        self.never_ready = never_ready
        self.calls = 0
        self.closed = False
        self.shut_write = False

    def recv_ready(self):
        return len(self.stdout_chunks) > 0

    def recv(self, size):
        if self.stdout_chunks:
            return self.stdout_chunks.pop(0)
        return b""

    def recv_stderr_ready(self):
        return len(self.stderr_chunks) > 0

    def recv_stderr(self, size):
        if self.stderr_chunks:
            return self.stderr_chunks.pop(0)
        return b""

    def exit_status_ready(self):
        if self.never_ready:
            return False
        self.calls += 1
        return self.calls > self.ready_after

    def recv_exit_status(self):
        return self.exit_code

    def close(self):
        self.closed = True

    def shutdown_write(self):
        self.shut_write = True


def test_drain_channel_large_stdout():
    # 5 chunks of 32 KB each = 160 KB
    chunks = [b"A" * 32768 for _ in range(5)]
    channel = MockDrainChannel(stdout_chunks=chunks, exit_code=0, ready_after=6)
    exit_code, out, err = su._drain_channel(channel, channel, "test_cmd", timeout=5)
    assert exit_code == 0
    assert len(out) == 160 * 1024
    assert out.startswith("AAAA")
    assert err == ""


def test_drain_channel_large_stderr():
    chunks = [b"E" * 32768 for _ in range(5)]
    channel = MockDrainChannel(stderr_chunks=chunks, exit_code=0, ready_after=6)
    exit_code, out, err = su._drain_channel(channel, channel, "test_cmd", timeout=5)
    assert exit_code == 0
    assert out == ""
    assert len(err) == 160 * 1024


def test_drain_channel_fair_interleaving():
    out_chunks = [b"out1\n", b"out2\n", b"out3\n"]
    err_chunks = [b"err1\n", b"err2\n", b"err3\n"]
    channel = MockDrainChannel(stdout_chunks=out_chunks, stderr_chunks=err_chunks, exit_code=0, ready_after=4)
    exit_code, out, err = su._drain_channel(channel, channel, "test_cmd", timeout=5)
    assert exit_code == 0
    assert out == "out1\nout2\nout3"
    assert err == "err1\nerr2\nerr3"


def test_drain_channel_memory_limit_bounded_and_truncated():
    # 2.5 MiB in chunks
    chunk = b"X" * 65536
    chunks = [b"START-HEADER\n"] + [chunk for _ in range(40)] + [b"\nFINAL-FOOTER"]
    channel = MockDrainChannel(stdout_chunks=chunks, exit_code=0, ready_after=45)
    exit_code, out, err = su._drain_channel(channel, channel, "test_cmd", timeout=5)
    assert exit_code == 0
    # Strict 1 MiB retention
    assert len(out.encode()) <= su.MAX_STREAM_BYTES
    assert "START-HEADER" in out
    assert "FINAL-FOOTER" in out
    assert "[... output truncated ...]" in out


def test_drain_channel_timeout_with_continuous_output(monkeypatch):
    class InfiniteChannel(MockDrainChannel):
        def recv_ready(self):
            return True

        def recv(self, size):
            return b"stream-data-never-stops\n"

        def exit_status_ready(self):
            return False

    clock = iter([0.0, 0.05, 0.1, 0.15, 10.0])
    monkeypatch.setattr(su.time, "monotonic", lambda: next(clock, 10.0))
    monkeypatch.setattr(su.time, "sleep", lambda s: None)

    channel = InfiniteChannel()
    with pytest.raises(su.RemoteTimeoutError, match="did not finish within 5s"):
        su._drain_channel(channel, channel, "infinite_cmd", timeout=5)
    assert channel.closed is True


def test_drain_channel_pending_bytes_after_exit_status_ready():
    # Channel immediately signals exit_status_ready=True, but chunks are still pending
    channel = MockDrainChannel(stdout_chunks=[b"first-chunk\n", b"second-chunk\n"], exit_code=0, ready_after=0)
    exit_code, out, err = su._drain_channel(channel, channel, "test_cmd", timeout=5)
    assert exit_code == 0
    assert out == "first-chunk\nsecond-chunk"


def test_drain_channel_closed_without_exit_status():
    channel = MockDrainChannel(never_ready=True)
    channel.closed = True
    with pytest.raises(su.RemoteCommandError, match="without a valid exit status"):
        su._drain_channel(channel, channel, "test_cmd", timeout=5)
    assert channel.closed is True


def test_drain_channel_invalid_negative_exit_status():
    channel = MockDrainChannel(exit_code=-1, ready_after=1)
    with pytest.raises(su.RemoteCommandError, match="invalid exit status -1"):
        su._drain_channel(channel, channel, "test_cmd", timeout=5)


def test_exec_impl_cleanup_on_error(monkeypatch):
    from unittest.mock import MagicMock
    channel = MockDrainChannel(never_ready=True)
    stdout = SimpleNamespace(channel=channel)
    stderr = SimpleNamespace(channel=channel)
    stdin = SimpleNamespace(write=lambda s: None, flush=lambda: None, channel=channel)

    client = MagicMock()
    client.exec_command.return_value = (stdin, stdout, stderr)

    clock = iter([0.0, 100.0])
    monkeypatch.setattr(su.time, "monotonic", lambda: next(clock, 100.0))
    monkeypatch.setattr(su.time, "sleep", lambda s: None)

    with pytest.raises(su.RemoteTimeoutError):
        su._exec_impl(client, "fail_cmd", timeout=5, sudo_pass=None)

    assert channel.closed is True
