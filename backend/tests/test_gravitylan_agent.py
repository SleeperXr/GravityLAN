"""Tests for the standalone gravitylan agent (agent/gravitylan-agent.py).

The agent module has a hyphenated filename, so it is loaded via importlib
rather than a normal import statement.
"""

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

AGENT_PATH = Path(__file__).resolve().parent.parent.parent / "agent" / "gravitylan-agent.py"


@pytest.fixture(scope="module")
def agent_mod() -> types.ModuleType:
    """Load the agent script as a module once per test module."""
    spec = importlib.util.spec_from_file_location("gravitylan_agent_under_test", AGENT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- AgentConfig ------------------------------------------------------------

def test_config_load_required_keys(agent_mod, tmp_path):
    cfg = tmp_path / "agent.conf"
    cfg.write_text('{"server_url": "192.168.1.10:8000", "token": "t", "device_id": 3}', encoding="utf-8")
    config = agent_mod.AgentConfig.load(cfg)
    assert config.server_url == "http://192.168.1.10:8000"  # scheme auto-added
    assert config.device_id == 3
    assert config.interval == 30  # default


def test_config_load_missing_key(agent_mod, tmp_path):
    cfg = tmp_path / "agent.conf"
    cfg.write_text('{"server_url": "http://x", "device_id": 1}', encoding="utf-8")
    with pytest.raises(KeyError):
        agent_mod.AgentConfig.load(cfg)


def test_config_load_invalid_json(agent_mod, tmp_path):
    cfg = tmp_path / "agent.conf"
    cfg.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError):
        agent_mod.AgentConfig.load(cfg)


def test_config_save_roundtrip(agent_mod, tmp_path):
    cfg = tmp_path / "agent.conf"
    config = agent_mod.AgentConfig(
        server_url="http://x", token="t", device_id=1, interval=15, config_path=cfg
    )
    config.save()
    loaded = agent_mod.AgentConfig.load(cfg)
    assert loaded.interval == 15


# --- is_lxc_container / get_lxc_cpu_count -----------------------------------

def test_is_lxc_container_false(agent_mod, tmp_path):
    assert agent_mod.is_lxc_container(str(tmp_path)) is False


def test_is_lxc_container_systemd_marker(agent_mod, tmp_path):
    marker = tmp_path / "run/systemd/container"
    marker.parent.mkdir(parents=True)
    marker.write_text("lxc", encoding="utf-8")
    assert agent_mod.is_lxc_container(str(tmp_path)) is True


def test_get_lxc_cpu_count_cgroup_v2(agent_mod, tmp_path):
    cpu_max = tmp_path / "sys/fs/cgroup/cpu.max"
    cpu_max.parent.mkdir(parents=True)
    cpu_max.write_text("100000 100000\n", encoding="utf-8")
    assert agent_mod.get_lxc_cpu_count(str(tmp_path)) == 1.0


def test_get_lxc_cpu_count_fallback(agent_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(agent_mod.os, "cpu_count", lambda: 8)
    assert agent_mod.get_lxc_cpu_count(str(tmp_path)) == 8


# --- PatchMetrics -----------------------------------------------------------

def _make_config(agent_mod):
    return agent_mod.AgentConfig(
        server_url="http://x", token="t", device_id=1, enable_patch_check=True
    )


def test_patch_metrics_disabled(agent_mod):
    config = _make_config(agent_mod)
    config.enable_patch_check = False
    assert agent_mod.PatchMetrics().collect(config) is None


def test_patch_metrics_apt(agent_mod):

    fake_shutil = SimpleNamespace(
        which=lambda name: "/usr/bin/apt-get" if name == "apt-get" else None
    )
    with patch.object(agent_mod, "_apt_cache_is_stale", return_value=False), \
         patch.object(agent_mod, "subprocess", SimpleNamespace(check_output=lambda *a, **k: b"Inst foo [1.0] (1.1 security) [a]\nInst bar [2.0] [b]\n", run=None, DEVNULL=None)), \
         patch.object(agent_mod.os.path, "exists", return_value=False), \
         patch.object(agent_mod, "shutil", fake_shutil):
        result = agent_mod.PatchMetrics().collect(_make_config(agent_mod))

    assert result["patch_manager"] == "apt"
    assert result["patch_available"] == 2
    assert result["patch_security"] == 1
    assert result["reboot_required"] is False


def test_patch_metrics_apt_reboot_flag(agent_mod):

    fake_shutil = SimpleNamespace(
        which=lambda name: "/usr/bin/apt-get" if name == "apt-get" else None
    )
    with patch.object(agent_mod, "_apt_cache_is_stale", return_value=False), \
         patch.object(agent_mod, "subprocess", SimpleNamespace(check_output=lambda *a, **k: b"", run=None, DEVNULL=None)), \
         patch.object(agent_mod.os.path, "exists", return_value=True), \
         patch.object(agent_mod, "shutil", fake_shutil):
        result = agent_mod.PatchMetrics().collect(_make_config(agent_mod))

    assert result["reboot_required"] is True


def test_patch_metrics_dnf(agent_mod):

    proc = MagicMock()
    proc.stdout = b"pkg1.x86_64 1.0 repo\npkg2.noarch 2.0 repo\n"
    proc_sec = MagicMock()
    proc_sec.stdout = b"Security fix 1\n"

    def fake_run(cmd, **kwargs):
        return proc_sec if "updateinfo" in cmd else proc

    fake_subprocess = SimpleNamespace(
        run=fake_run, check_output=lambda *a, **k: b"", PIPE=-1, DEVNULL=None
    )
    fake_shutil = SimpleNamespace(
        which=lambda name: "/usr/bin/dnf" if name == "dnf" else None
    )
    with patch.object(agent_mod, "subprocess", fake_subprocess), \
         patch.object(agent_mod, "shutil", fake_shutil):
        result = agent_mod.PatchMetrics().collect(_make_config(agent_mod))

    assert result["patch_manager"] == "dnf"
    assert result["patch_available"] == 2
    assert result["patch_security"] == 1


def test_patch_metrics_unknown_manager(agent_mod):

    fake_shutil = SimpleNamespace(which=lambda name: None)
    with patch.object(agent_mod, "shutil", fake_shutil):
        assert agent_mod.PatchMetrics().collect(_make_config(agent_mod)) is None


# --- DiskMetrics ------------------------------------------------------------

def test_disk_metrics_uses_zfs_stats(agent_mod, monkeypatch):
    monkeypatch.setattr(
        agent_mod, "_collect_zfs_stats",
        lambda: {"/data": {"used": 10 * 1024**3, "avail": 30 * 1024**3, "refer": 0}},
    )
    config = _make_config(agent_mod)
    config.disk_paths = ["/data"]

    result = agent_mod.DiskMetrics().collect(config)
    assert len(result) == 1
    assert result[0]["path"] == "/data"
    assert result[0]["total_gb"] == 40.0


def test_disk_metrics_statvfs_fallback(agent_mod, monkeypatch):

    monkeypatch.setattr(agent_mod, "_collect_zfs_stats", lambda: {})

    fake_os = SimpleNamespace(
        statvfs=lambda p: MagicMock(
            f_blocks=10 * 1024**3 // 4096,
            f_frsize=4096,
            f_files=1000,
            f_bavail=8 * 1024**3 // 4096,
        ),
        getenv=agent_mod.os.getenv,
    )
    monkeypatch.setattr(agent_mod, "os", fake_os)

    config = _make_config(agent_mod)
    config.disk_paths = ["/mnt"]

    result = agent_mod.DiskMetrics().collect(config)
    assert len(result) == 1
    assert result[0]["total_gb"] == 10.0
    assert result[0]["used_gb"] == 2.0


def test_disk_metrics_skips_unreadable(agent_mod, monkeypatch):

    monkeypatch.setattr(agent_mod, "_collect_zfs_stats", lambda: {})

    def fake_statvfs(path):
        raise PermissionError("nope")

    fake_os = SimpleNamespace(statvfs=fake_statvfs, getenv=agent_mod.os.getenv)
    monkeypatch.setattr(agent_mod, "os", fake_os)

    config = _make_config(agent_mod)
    config.disk_paths = ["/nope"]

    assert agent_mod.DiskMetrics().collect(config) == []


# --- ReportSender / Orchestrator --------------------------------------------

def test_report_sender_success(agent_mod):
    config = _make_config(agent_mod)
    sender = agent_mod.ReportSender(config)
    payload = {"device_id": 1}

    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = b'{"ok": true}'

    with patch.object(agent_mod.urllib.request, "urlopen", return_value=resp):
        result = sender.send(payload)

    assert result == {"ok": True}
    assert sender.consecutive_failures == 0


def test_report_sender_backoff_on_error(agent_mod):
    from urllib.error import URLError

    config = _make_config(agent_mod)
    sender = agent_mod.ReportSender(config)

    with patch.object(agent_mod.urllib.request, "urlopen", side_effect=URLError("down")):
        assert sender.send({"device_id": 1}) is None

    assert sender.consecutive_failures == 1


def test_orchestrator_collect_all(agent_mod, monkeypatch):

    fake_os = SimpleNamespace(
        statvfs=lambda p: MagicMock(
            f_blocks=10 * 1024**3 // 4096,
            f_frsize=4096,
            f_files=1000,
            f_bavail=8 * 1024**3 // 4096,
        ),
        getenv=agent_mod.os.getenv,
    )
    monkeypatch.setattr(agent_mod, "os", fake_os)
    # Behave like a Linux host with apt on every OS, so an unmocked patch
    # collector would fail here too instead of only on the Linux CI runner.
    monkeypatch.setattr(agent_mod.shutil, "which", lambda name: f"/usr/bin/{name}")

    config = _make_config(agent_mod)
    orch = agent_mod.AgentOrchestrator(config)
    patches = {"patch_available": 3, "patch_security": 1, "patch_manager": "apt"}

    # The patch collector shells out to apt/dnf/yum; never run real package managers in tests.
    with patch.object(orch.collectors["system"], "collect", return_value={"os": "TestOS"}), \
         patch.object(orch.collectors["temperature"], "collect", return_value=None), \
         patch.object(orch.collectors["patches"], "collect", return_value=patches):
        payload = orch.collect_all()

    assert payload["device_id"] == 1
    assert payload["system"] == {"os": "TestOS"}
    assert payload["patches"] == patches
    assert "temperature" not in payload


def test_orchestrator_process_response_updates_config(agent_mod):
    config = _make_config(agent_mod)
    orch = agent_mod.AgentOrchestrator(config)
    orch.config.save = MagicMock()

    orch.process_response({
        "device_id": 42,
        "config": {"interval": 60, "enable_temp": False},
    })

    assert orch.config.device_id == 42
    assert orch.config.interval == 60
    assert orch.config.enable_temp is False
    orch.config.save.assert_called_once()
