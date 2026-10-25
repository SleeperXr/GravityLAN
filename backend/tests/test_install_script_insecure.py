"""The manual installer refuses plain HTTP unless ALLOW_INSECURE=1 (#44)."""
import os
import shutil
import subprocess
import sys

import pytest

from app.models.device import Device
from app.models.setting import Setting
from app.services.agent_scripts import build_install_script

HEADERS = {"Authorization": "Bearer test-admin-token-12345"}
BASH = shutil.which("bash")
# On Windows "bash" may be WSL's launcher, which does not see this environment
needs_bash = pytest.mark.skipif(
    not BASH or (sys.platform == "win32" and "system32" in BASH.lower()), reason="needs a POSIX bash"
)


def _run(script: str, tmp_path, **env) -> subprocess.CompletedProcess:
    """Run the installer with a curl stub that records every download."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    curl = bin_dir / "curl"
    curl.write_text(f'#!/bin/sh\necho "$@" >> "{(tmp_path / "curl.log").as_posix()}"\nexit 1\n', newline="\n")
    curl.chmod(0o755)
    run_env = {**os.environ, **env, "PATH": f"{bin_dir.as_posix()}{os.pathsep}{os.environ.get('PATH', '')}"}
    return subprocess.run([BASH, "-s"], input=script, env=run_env, capture_output=True, text=True, timeout=30)


@needs_bash
def test_http_install_is_refused_before_any_download(tmp_path):
    result = _run(build_install_script("http://192.168.1.5:8000", 3, "abc"), tmp_path)
    assert result.returncode == 1
    assert "plain HTTP" in result.stderr
    assert "ALLOW_INSECURE=1" in result.stderr
    assert "HTTPS" in result.stderr and "SSH" in result.stderr
    assert not (tmp_path / "curl.log").exists()


@needs_bash
def test_http_install_continues_with_opt_in(tmp_path):
    result = _run(build_install_script("http://192.168.1.5:8000", 3, "abc"), tmp_path, ALLOW_INSECURE="1")
    assert "WARNING: installing over plain HTTP" in result.stderr
    assert "Error: the GravityLAN server address" not in result.stderr


@needs_bash
def test_https_install_needs_no_opt_in(tmp_path):
    result = _run(build_install_script("https://gravity.example", 3, "abc"), tmp_path)
    assert "plain HTTP" not in result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("server_url,insecure", [("http://gravity.example:9000", True), ("https://gravity.example", False)])
async def test_enrollment_reports_insecure_server_url(client, db, admin_token, server_url, insecure):
    device = Device(ip="192.168.1.90", display_name="Pi", is_online=True)
    db.add_all([device, Setting(key="server.url", value=server_url)])
    await db.commit()

    res = await client.post(f"/api/agent/enroll/{device.id}", headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["insecure"] is insecure


@needs_bash
def test_server_wide_opt_in_allows_http_with_warning(tmp_path):
    result = _run(build_install_script("http://192.168.1.5:8000", 3, "abc", allow_insecure=True), tmp_path)
    assert "WARNING: installing over plain HTTP" in result.stderr
    assert "Error: the GravityLAN server address" not in result.stderr


def test_server_wide_opt_in_follows_the_setting(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "allow_insecure_install", True)
    assert 'ALLOW_INSECURE="${ALLOW_INSECURE:-1}"' in build_install_script("http://h:8000", 1, "c")
    monkeypatch.setattr(settings, "allow_insecure_install", False)
    assert "ALLOW_INSECURE:-1" not in build_install_script("http://h:8000", 1, "c")
