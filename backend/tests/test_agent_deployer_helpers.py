"""Helpers of the SSH agent deployment (app/services/agent_deployer.py): probes, install paths, nohup fallback,
error messages and the local agent file."""

import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import paramiko
import pytest

import app.services.agent_deployer as dep
from app.services.ssh_utils import HostKeyNotTrusted


class FakeClient:
    """exec_command answers by command substring; records every command."""

    def __init__(self, answers=None, exit_codes=None, raise_on=None):
        self.answers = answers or {}
        self.exit_codes = exit_codes or {}
        self.raise_on = raise_on
        self.commands = []

    def exec_command(self, cmd, timeout=None):
        self.commands.append(cmd)
        if self.raise_on and self.raise_on in cmd:
            raise self.raise_on_exc
        out = next((v for k, v in self.answers.items() if k in cmd), "")
        code = next((v for k, v in self.exit_codes.items() if k in cmd), 0)
        stdout = SimpleNamespace(read=lambda: out.encode() if isinstance(out, str) else out,
                                 channel=SimpleNamespace(recv_exit_status=lambda: code))
        return None, stdout, None


# --- probes ------------------------------------------------------------------------------------

def test_python_probe_uses_which_or_falls_back():
    assert dep._probe_python(FakeClient({"which python3": "/usr/bin/python3\n"})) == "/usr/bin/python3"
    assert dep._probe_python(FakeClient(exit_codes={"which python3": 1})) == "python3"
    broken = FakeClient(raise_on="which")
    broken.raise_on_exc = OSError("closed")
    assert dep._probe_python(broken) == "python3"


@pytest.mark.parametrize(("answers", "expected"), [
    ({}, (False, False)),
    ({"/run/systemd/system": "systemd\n"}, (True, False)),
    ({"synoinfo": "synology"}, (False, True)),
    ({"/run/systemd/system": "systemd", "synoinfo": "synology"}, (True, True)),
])
def test_platform_probe(answers, expected):
    assert dep._probe_platform(FakeClient(answers), "10.0.0.5") == expected


def test_sudo_unraid_and_running_checks():
    assert dep._check_sudo(FakeClient()) is True
    assert dep._check_sudo(FakeClient(exit_codes={"which sudo": 1})) is False
    assert dep._is_unraid(FakeClient({"unraid-version": "unraid\n"})) is True
    assert dep._is_unraid(FakeClient()) is False
    assert dep._is_agent_running(FakeClient({"ps aux": "root 1 python3 /opt/x/agent.py"}), "/opt/x/agent.py") is True
    assert dep._is_agent_running(FakeClient(), "/opt/x/agent.py") is False


def test_ssh_connected_check():
    alive = SimpleNamespace(get_transport=lambda: SimpleNamespace(is_active=lambda: True))
    dead = SimpleNamespace(get_transport=lambda: SimpleNamespace(is_active=lambda: False))
    assert dep._is_ssh_connected(alive) is True
    assert dep._is_ssh_connected(dead) is False
    assert dep._is_ssh_connected(None) is False


# --- checksum ----------------------------------------------------------------------------------

def test_remote_checksum_matches_mismatches_and_unknown_answers():
    assert dep._verify_remote_sha256(FakeClient({"sha256sum": "abc\n"}), "/tmp/a", "abc") is True
    assert dep._verify_remote_sha256(FakeClient({"sha256sum": "def\n"}), "/tmp/a", "abc") is False

    class NoTimeout(FakeClient):
        def exec_command(self, cmd, timeout=None):
            raise ValueError("old client without timeout")

    # Fail closed: a digest that cannot be read is no match
    assert dep._verify_remote_sha256(NoTimeout(), "/tmp/a", "abc") is False
    odd = FakeClient()
    odd.exec_command = lambda cmd, timeout=None: (None, SimpleNamespace(read=lambda: MagicMock()), None)
    assert dep._verify_remote_sha256(odd, "/tmp/a", "abc") is False


# --- install paths -----------------------------------------------------------------------------

@pytest.fixture
def staged(monkeypatch):
    files = {}
    monkeypatch.setattr(dep, "_stage_file", lambda client, path, content: files.__setitem__(path, content))
    return files


def _deploy_ctx(client=None, runner=None, device_id=7, base_dir="/opt/a", agent_path="/opt/a/agent.py", server_url="http://srv"):
    """Create a minimal _Deployment fixture for helper unit tests."""
    return dep._Deployment(
        client=client,
        runner=runner,
        host_ip="h",
        device_id=device_id,
        base_dir=base_dir,
        server_url=server_url,
        token="t",
        agent_path=agent_path,
    )


def test_systemd_install_stages_the_unit_and_reports_failure(staged):
    """Ensure systemd unit staging succeeds and sudo batch errors return False."""
    runner = SimpleNamespace(batches=[], run_sudo_batch=None)
    runner.run_sudo_batch = lambda cmds: runner.batches.append(cmds)
    assert dep._install_systemd_service(_deploy_ctx(runner=runner), "/usr/bin/python3") is True
    assert "/tmp/gravitylan_service_7.service" in staged
    assert "ExecStart" in staged["/tmp/gravitylan_service_7.service"]
    assert any("systemctl restart gravitylan-agent" in c for c in runner.batches[0])

    def refuse(_cmds):
        raise RuntimeError("sudo: a password is required")

    failing_ctx = _deploy_ctx(runner=SimpleNamespace(run_sudo_batch=refuse), base_dir="/b", agent_path="/a")
    assert dep._install_systemd_service(failing_ctx, "python3") is False


def test_synology_install_writes_the_rc_script(staged):
    runner = SimpleNamespace(batches=[])
    runner.run_sudo_batch = lambda cmds: runner.batches.append(cmds)
    dep._install_syno_rc(_deploy_ctx(runner=runner, device_id=3), "/bin/python3")
    script = staged["/tmp/gravitylan_rc_3.sh"]
    assert "cd /opt/a || exit 1" in script
    assert "/bin/python3 /opt/a/agent.py > /opt/a/gravitylan-agent.log 2>&1 < /dev/null &" in script
    assert "pkill -f /opt/a/agent.py" in script
    assert "{start|stop|restart}" in script
    assert runner.batches[0][-1] == "/usr/local/etc/rc.d/S99gravitylan-agent.sh restart || true"


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_synology_start_does_not_keep_the_ssh_output_open(staged, tmp_path):
    """The channel only ends once nobody holds its output: an attached agent made every deploy time out."""
    runner = SimpleNamespace(run_sudo_batch=lambda cmds: None)
    # A short sleep stands in for the agent, which keeps running after the script returns
    dep._install_syno_rc(_deploy_ctx(runner=runner, device_id=3, base_dir=tmp_path.as_posix(), agent_path="8"), "sleep")
    script = tmp_path / "rc.sh"
    script.write_bytes(staged["/tmp/gravitylan_rc_3.sh"].encode())
    subprocess.run(["sh", script.as_posix(), "start"], capture_output=True, timeout=4, check=True)


def test_agent_config_json():
    import json

    cfg = json.loads(dep._build_agent_config("http://srv:8000", "tok", 5))
    assert cfg == {"server_url": "http://srv:8000", "token": "tok", "device_id": 5, "interval": 30,
                   "disk_paths": ["/"], "enable_temp": True}


def test_nohup_fallback_reports_start_or_failure(monkeypatch):
    """Verify nohup fallback return tuple on process start, log error, or silent failure."""
    monkeypatch.setattr(dep.time, "sleep", lambda s: None)
    ok = FakeClient({"ps aux": "python3 /opt/a/agent.py"})
    assert dep._nohup_fallback(_deploy_ctx(client=ok), "python3") == (
        True, "Agent started (Nohup fallback, URL: http://srv)")
    assert any("nohup python3 /opt/a/agent.py" in c for c in ok.commands)
    assert any(c.startswith("pkill -f '[/]opt") for c in ok.commands)

    with_log = FakeClient({"tail -n 20": "Traceback: boom"})
    success, msg = dep._nohup_fallback(_deploy_ctx(client=with_log, server_url="u"), "python3")
    assert success is False and "Check the server log" in msg

    silent = FakeClient()
    success, msg = dep._nohup_fallback(_deploy_ctx(client=silent, server_url="u"), "python3")
    assert success is False and msg.endswith("both failed).")


# --- SSH errors --------------------------------------------------------------------------------

@pytest.mark.parametrize("strict", [False, True])
def test_ssh_errors_become_readable_messages(monkeypatch, strict):
    from app.config import settings

    monkeypatch.setattr(settings, "ssh_strict_mode", strict)
    ok, msg = dep._map_ssh_error(HostKeyNotTrusted("x"), "10.0.0.5")
    assert ok is False and msg.startswith(dep.HOST_KEY_CHANGED_PREFIX) and dep.is_host_key_refusal(msg)
    assert dep._map_ssh_error(paramiko.AuthenticationException("no"), "h")[1] == "SSH authentication failed. Please check your credentials."

    key = MagicMock()
    key.get_base64.return_value = "AAAA"
    ok, msg = dep._map_ssh_error(paramiko.ssh_exception.BadHostKeyException("h", key, key), "10.0.0.5")
    assert "does not match the stored key" in msg and ("Strict Mode" in msg) == strict

    ok, msg = dep._map_ssh_error(paramiko.SSHException("Server 'h' not found in known_hosts"), "10.0.0.5")
    assert msg.startswith("SSH connection rejected: Unknown host key") and ("Strict Mode" in msg) == strict
    assert dep._map_ssh_error(paramiko.SSHException("timeout"), "h")[1].startswith("SSH connection failed")
    assert dep._map_ssh_error(ValueError("not ssh"), "h") is None


# --- local agent file --------------------------------------------------------------------------

def test_version_and_checksum_of_the_local_agent_file(monkeypatch, tmp_path):
    script = tmp_path / "gravitylan-agent.py"
    monkeypatch.setattr(dep, "AGENT_SCRIPT_PATH", tmp_path / "missing.py")
    assert dep.get_latest_agent_version() == "0.2.5"
    assert dep.get_agent_script_sha256() == ""

    script.write_text('# agent\nVERSION = "1.2.3"\n', encoding="utf-8")
    monkeypatch.setattr(dep, "AGENT_SCRIPT_PATH", script)
    assert dep.get_latest_agent_version() == "1.2.3"
    assert len(dep.get_agent_script_sha256()) == 64

    script.write_text("# no version here\n", encoding="utf-8")
    assert dep.get_latest_agent_version() == "0.2.5"
    assert dep._parse_version_line("VERSION = '0.9'") == "0.9"
    assert dep._parse_version_line("nothing") is None


def test_ssh_error_mapping_for_remote_command_and_network_errors():
    """Verify _map_ssh_error formats RemoteCommandError and TimeoutError messages."""
    from app.services.ssh_utils import RemoteCommandError

    assert dep._map_ssh_error(RemoteCommandError("sudo failed"), "10.0.0.5") == (False, "sudo failed")
    ok, msg = dep._map_ssh_error(TimeoutError("timed out"), "10.0.0.5")
    assert ok is False and "TimeoutError" in msg


def test_version_and_checksum_handle_oserror_and_script_path_fallbacks(monkeypatch, tmp_path):
    """Verify OSError fallbacks when reading local script version/checksum and path resolution."""
    bad_dir = tmp_path / "is_a_dir"
    bad_dir.mkdir()
    monkeypatch.setattr(dep, "AGENT_SCRIPT_PATH", bad_dir)
    assert dep.get_latest_agent_version() == "0.2.5"
    assert dep.get_agent_script_sha256() == ""

    monkeypatch.setattr(dep.Path, "exists", lambda self: False)
    assert dep.get_agent_script_path() == dep.Path("/app/agent/gravitylan-agent.py")
    monkeypatch.setattr(dep.Path, "exists", lambda self: str(self).replace("\\", "/") == "/app/agent/gravitylan-agent.py")
    assert dep.get_agent_script_path() == dep.Path("/app/agent/gravitylan-agent.py")


def test_client_for_pinned_and_tofu_and_blocking_error_paths(monkeypatch):
    """Verify _client_for policies and error handling in blocking deploy/remove entrypoints."""
    from app.config import settings
    from app.services.ssh_utils import PinnedHostKey, TofuHostKeyPolicy

    monkeypatch.setattr(settings, "ssh_strict_mode", False)
    sentinel_pinned = MagicMock()
    monkeypatch.setattr(dep, "build_pinned_ssh_client", lambda pk: sentinel_pinned)
    assert dep._client_for(PinnedHostKey("ssh-ed25519", "AAAA")) is sentinel_pinned

    fake_client = MagicMock()
    monkeypatch.setattr(dep, "build_ssh_client", lambda: fake_client)
    policy = TofuHostKeyPolicy()
    assert dep._client_for(None, policy) is fake_client
    fake_client.set_missing_host_key_policy.assert_called_once_with(policy)

    monkeypatch.setattr(dep, "build_connect_kwargs", lambda *a, **k: (None, "invalid key"))
    assert dep._deploy_agent_blocking(
        host_ip="h", ssh_user="u", ssh_password=None, ssh_key="bad", ssh_port=22, server_url="http://s", device_id=1,
    ) == (False, "invalid key", "")
    assert dep._remove_agent_blocking(
        host_ip="h", ssh_user="u", ssh_password=None, ssh_key="bad", ssh_port=22,
    ) == (False, "invalid key")

    monkeypatch.setattr(dep, "build_connect_kwargs", lambda *a, **k: ({}, None))
    monkeypatch.setattr(dep, "connect_with_gateway_fallback", lambda *a, **k: None)
    monkeypatch.setattr(dep, "_check_sudo", lambda c: True)
    runner = MagicMock()
    monkeypatch.setattr(dep, "RemoteRunner", lambda *a, **k: runner)
    assert dep._remove_agent_blocking(
        host_ip="h", ssh_user="u", ssh_password="pw", ssh_key=None, ssh_port=22,
    )[0] is True
    runner.run_sudo_batch.assert_called_once()

    def boom(*_a, **_k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(dep, "connect_with_gateway_fallback", boom)
    assert dep._deploy_agent_blocking(
        host_ip="h", ssh_user="u", ssh_password="pw", ssh_key=None, ssh_port=22, server_url="http://s", device_id=1,
    ) == (False, "Deployment failed due to an unexpected internal error.", "")
    assert dep._remove_agent_blocking(
        host_ip="h", ssh_user="u", ssh_password="pw", ssh_key=None, ssh_port=22,
    ) == (False, "Deinstallation failed due to an unexpected internal error.")
