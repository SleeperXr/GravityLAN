"""The steps _deploy_agent_blocking is built from (app/services/agent_deployer.py): staging the
verified script, installing files and the service, and starting or falling back to nohup."""

from unittest.mock import MagicMock

import pytest

import app.services.agent_deployer as dep


@pytest.fixture
def script(tmp_path, monkeypatch):
    path = tmp_path / "gravitylan-agent.py"
    path.write_text("print('agent')", encoding="utf-8")
    monkeypatch.setattr(dep, "AGENT_SCRIPT_PATH", path)
    monkeypatch.setattr(dep, "_stage_file", lambda *a, **k: None)
    return path


def test_stage_verified_agent(script, monkeypatch):
    runner = MagicMock()
    monkeypatch.setattr(dep, "_verify_remote_sha256", lambda client, path, digest: True)
    assert dep._stage_verified_agent(MagicMock(), runner, 7) == "/tmp/gravitylan_agent_7.py"
    runner.run.assert_not_called()

    monkeypatch.setattr(dep, "_verify_remote_sha256", lambda client, path, digest: False)
    assert dep._stage_verified_agent(MagicMock(), runner, 7) is None
    runner.run.assert_called_once_with("rm -f /tmp/gravitylan_agent_7.py || true")


def _deployment(client=None, runner=None, server_url="http://gl:8000", agent_path=dep.REMOTE_AGENT_PATH):
    """Build a test _Deployment context with mocked SSH client and runner defaults."""
    return dep._Deployment(
        client=client or MagicMock(),
        runner=runner or MagicMock(),
        host_ip="192.0.2.10",
        device_id=7,
        base_dir="/opt/gl",
        server_url=server_url,
        token="tok",
        agent_path=agent_path,
    )


def test_install_agent_files_cleans_up_moves_and_writes_an_owner_only_config(monkeypatch):
    runner = MagicMock()
    monkeypatch.setattr(dep, "_probe_platform", lambda client, ip: (True, False))
    monkeypatch.setattr(dep, "_stage_file", lambda *a, **k: None)
    platform = dep._install_agent_files(_deployment(runner=runner), "/tmp/a.py")
    assert platform == (True, False)
    runner.run_sudo_batch.assert_called_once()
    commands = [c.args[0] for c in runner.run.call_args_list]
    assert commands[0] == "mkdir -p /opt/gl"
    assert commands[1].startswith("mv /tmp/a.py ")
    assert commands[2].endswith(f"chmod 600 {dep.REMOTE_CONFIG_PATH}")


@pytest.mark.parametrize("systemd, syno, expected", [(True, False, "systemd"), (False, True, "syno"), (False, False, None)])
def test_install_service_picks_the_init_system(monkeypatch, systemd, syno, expected):
    """Verify that _install_service dispatches to systemd, Synology rc.d, or neither."""
    called = []
    monkeypatch.setattr(dep, "_install_systemd_service", lambda *a: called.append("systemd") or True)
    monkeypatch.setattr(dep, "_install_syno_rc", lambda *a: called.append("syno"))
    dep._install_service(_deployment(), "python3", systemd, syno)
    assert called == ([expected] if expected else [])


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(dep.time, "sleep", lambda s: None)


def test_start_and_verify_when_the_service_already_runs(no_wait, monkeypatch):
    monkeypatch.setattr(dep, "_is_agent_running", lambda client, path: True)
    ok, message, token = dep._start_and_verify(_deployment(), "python3", "")
    assert (ok, token) == (True, "tok")
    assert message == "Agent started successfully (Directory: /opt/gl, URL: http://gl:8000)"


def test_start_and_verify_reports_a_failed_nohup_start(no_wait, monkeypatch):
    monkeypatch.setattr(dep, "_is_agent_running", lambda client, path: False)
    monkeypatch.setattr(dep, "_nohup_fallback", lambda *a: (False, "python3 not found"))
    result = dep._start_and_verify(_deployment(server_url="u"), "python3", "")
    assert result == (False, "python3 not found", "")
