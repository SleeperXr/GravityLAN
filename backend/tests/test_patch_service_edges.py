"""Edges of patch_service the happy-path tests leave out: host-key policies, login problems,
the Docker gateway retry, a missing transport and hosts without a known package manager.
"""

import logging
from unittest.mock import MagicMock, patch

import paramiko
import pytest

from app.config import settings
from app.services import patch_service as ps

HOST = "192.0.2.5"
GATEWAY = "172.17.0.1"
NOTHING_FOUND = {"patch_manager": None, "packages": [], "major_upgrade_available": None}


def _stdout(text: str) -> MagicMock:
    stdout = MagicMock()
    stdout.read.return_value = text.encode()
    return stdout


def _shell(outputs: dict[str, str] | None = None) -> MagicMock:
    """SSH client double: exec_command answers from ``outputs`` by command prefix, else prints nothing."""
    client = MagicMock()

    def exec_command(cmd, timeout=None):
        text = next((out for prefix, out in (outputs or {}).items() if cmd.startswith(prefix)), "")
        return None, _stdout(text), None

    client.exec_command.side_effect = exec_command
    return client


def _update_channel(chunks: list[bytes], exit_code: int) -> MagicMock:
    """``apt-get update`` channel that hands out ``chunks``, then reports ``exit_code``."""
    chan = MagicMock(spec=paramiko.Channel)
    chan.recv_ready.side_effect = lambda: bool(chunks)
    chan.recv.side_effect = lambda _n: chunks.pop(0)
    chan.exit_status_ready.side_effect = lambda: not chunks
    chan.recv_exit_status.return_value = exit_code
    return chan


@pytest.fixture
def query(monkeypatch):
    """Runs the blocking update query against a client double."""

    def run(client, **overrides):
        monkeypatch.setattr(ps, "_build_client", lambda **_kw: client)
        login = {"host_ip": HOST, "ssh_user": "root", "ssh_password": "pw", "ssh_key": None, "ssh_port": 22}
        return ps._list_device_updates_blocking(**{**login, **overrides})

    return run


# --- host-key policy -------------------------------------------------------------------

def test_a_pinned_key_decides_the_client(monkeypatch):
    pinned, built = object(), object()
    monkeypatch.setattr(ps, "build_pinned_ssh_client", lambda key: built if key is pinned else None)
    assert ps._build_client(pinned_host_key=pinned) is built


@patch("paramiko.SSHClient")
def test_strict_mode_rejects_unknown_hosts(_ssh_client, monkeypatch):
    monkeypatch.setattr(settings, "ssh_strict_mode", True)
    client = ps._build_client()
    client.load_system_host_keys.assert_called_once()
    assert isinstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.RejectPolicy)


# --- login -----------------------------------------------------------------------------

def test_the_repr_of_a_login_leaves_the_secrets_out():
    text = repr(ps._SshLogin(HOST, "oliver", 22, "hunter2", "PEMDATA", "phrase"))
    assert HOST in text and "oliver" in text
    for secret in ("hunter2", "PEMDATA", "phrase"):
        assert secret not in text


@pytest.mark.parametrize(("user", "needs_sudo", "sudo_password"), [("root", False, None), ("oliver", True, "pw")])
def test_only_non_root_logins_go_through_sudo(user, needs_sudo, sudo_password):
    login = ps._SshLogin(HOST, user, ssh_password="pw")
    assert (login.needs_sudo, login.sudo_password) == (needs_sudo, sudo_password)


def test_no_credentials_stop_before_connecting(query):
    client = _shell()
    assert query(client, ssh_password=None) == {**NOTHING_FOUND, "error": "Neither password nor SSH key provided."}
    client.connect.assert_not_called()
    client.close.assert_called_once()


def test_an_unreadable_key_is_reported_and_never_connects(query, monkeypatch):
    def refuse(_text, _passphrase):
        raise ValueError("not a private key")

    monkeypatch.setattr(ps, "_load_ssh_key", refuse)
    client = _shell()
    assert query(client, ssh_key="garbage") == {**NOTHING_FOUND, "error": "Invalid SSH key format: not a private key"}
    client.connect.assert_not_called()


def test_a_key_wins_over_the_password(query, monkeypatch):
    key, seen = object(), []
    monkeypatch.setattr(ps, "_load_ssh_key", lambda text, passphrase: seen.append((text, passphrase)) or key)
    client = _shell()
    query(client, ssh_key="PEM", ssh_key_passphrase="phrase", ssh_port=2222)
    assert seen == [("PEM", "phrase")]
    assert client.connect.call_args.kwargs == {"hostname": HOST, "port": 2222, "username": "root", "timeout": 15, "pkey": key}


def test_a_password_login_connects_with_it(query):
    client = _shell()
    query(client, ssh_user="oliver")
    assert client.connect.call_args.kwargs == {"hostname": HOST, "port": 22, "username": "oliver", "timeout": 15, "password": "pw"}


async def test_the_update_stream_stops_on_missing_credentials(monkeypatch):
    client = _shell()
    monkeypatch.setattr(ps, "_build_client", lambda **_kw: client)
    outcome = await ps.run_ssh_command_stream(host_ip=HOST, ssh_user="root", command="true", output_callback=print)
    assert outcome == (False, "Neither password nor SSH key provided.")
    client.connect.assert_not_called()
    client.close.assert_called_once()


# --- connecting ------------------------------------------------------------------------

def test_the_docker_host_is_retried_on_the_gateway(monkeypatch):
    monkeypatch.setattr(ps, "host_bypass_gateway", lambda _ip: GATEWAY)
    client = MagicMock()
    client.connect.side_effect = [TimeoutError("macvlan: host not reachable"), None]
    ps._connect_with_fallback(client, {"hostname": HOST}, HOST)
    assert [c.kwargs["hostname"] for c in client.connect.call_args_list] == [HOST, GATEWAY]


def test_no_transport_means_no_channel():
    client = MagicMock()
    client.get_transport.return_value = None
    assert ps._open_command_channel(client, {"hostname": HOST}, HOST, "uptime") is None


def test_a_connection_failure_is_returned_not_raised(query):
    client = _shell()
    client.connect.side_effect = OSError("no route to host")
    assert query(client) == {**NOTHING_FOUND, "error": "no route to host"}
    client.close.assert_called_once()


# --- package managers ------------------------------------------------------------------

def test_a_host_without_a_package_manager_reports_its_os(query):
    client = _shell({"cat /etc/os-release": 'PRETTY_NAME="Alpine Linux"\n'})
    assert query(client) == {**NOTHING_FOUND, "detected_os": 'PRETTY_NAME="Alpine Linux"'}


def test_a_failing_os_probe_only_loses_the_hint(query):
    client = MagicMock()
    client.exec_command.side_effect = [(None, _stdout(""), None), OSError("channel closed")]
    assert query(client) == {**NOTHING_FOUND, "detected_os": None}


def test_a_yum_host_lists_its_updates(query):
    client = _shell({"command -v": "/usr/bin/yum\n", "yum check-update": "curl.x86_64  7.81.0-1  updates\n"})
    package = {"package": "curl", "new_version": "7.81.0-1", "repo": "updates", "current_version": "Installed"}
    assert query(client) == {**NOTHING_FOUND, "patch_manager": "yum", "packages": [package]}


# --- apt-get update outcome ------------------------------------------------------------

def _apt_host(chan: MagicMock) -> MagicMock:
    client = _shell({"command -v": "/usr/bin/apt-get\n"})
    client.get_transport.return_value.open_session.return_value = chan
    return client


def test_a_failed_refresh_logs_its_output_and_blames_the_missing_password(query, monkeypatch, caplog):
    monkeypatch.setattr(ps, "_load_ssh_key", lambda _text, _passphrase: object())
    client = _apt_host(_update_channel([b"E: The repository is not signed.\n"], 100))
    with caplog.at_level(logging.WARNING, logger=ps.logger.name):
        res = query(client, ssh_user="oliver", ssh_password=None, ssh_key="PEM")
    assert res["error"] == (
        "apt-get update failed (exit 100). Set an SSH password or enable passwordless sudo to refresh package lists."
    )
    assert HOST in caplog.text
    assert "E: The repository is not signed." in caplog.text


def test_a_rejected_sudo_password_names_the_host_and_the_user(query, caplog):
    client = _apt_host(_update_channel([b"SUDOPROMPT:", b"SUDOPROMPT:"], 1))
    with caplog.at_level(logging.WARNING, logger=ps.logger.name):
        res = query(client, ssh_user="oliver", ssh_password="wrong")
    assert res["sudo_rejected"] is True
    assert res["error"] == (
        f"Sudo password rejected on {HOST} for user 'oliver'. "
        "Please check your SSH/sudo password or enable passwordless sudo."
    )
    assert "sudo rejected password for user 'oliver'" in caplog.text
