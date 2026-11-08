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
