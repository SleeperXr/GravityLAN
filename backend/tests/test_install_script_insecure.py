"""The manual installer refuses plain HTTP unless ALLOW_INSECURE=1 (#44)."""
import os
import shutil
import subprocess
import sys

import pytest

from app.models.device import Device
from app.models.setting import Setting
from app.services.session_service import session_store
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

    client.cookies.set("gravitylan_token", session_store.create_session(user_agent=None))
    res = await client.post(f"/api/agent/enroll/{device.id}")
    assert res.status_code == 200
    assert res.json()["insecure"] is insecure
    # The UI fetches the install script from the same address the script downloads from
    assert res.json()["server_url"] == server_url
    assert res.json()["insecure_allowed"] is False


@pytest.mark.asyncio
async def test_enrollment_reports_server_wide_opt_in(client, db, admin_token, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "allow_insecure_install", True)
    device = Device(ip="192.168.1.91", display_name="Pi", is_online=True)
    db.add(device)
    await db.commit()

    client.cookies.set("gravitylan_token", session_store.create_session(user_agent=None))
    res = await client.post(f"/api/agent/enroll/{device.id}")
    assert res.json()["insecure_allowed"] is True


def test_https_install_does_not_follow_redirects_to_http():
    script = build_install_script("https://gravity.example", 3, "abc")
    # Both downloads (agent and its token) stay on HTTPS, also across redirects
    assert script.count("curl --proto '=https' -fsSL \"$SERVER_URL/api/agent/download/") == 2


def test_http_install_script_has_no_https_restriction():
    assert "--proto" not in build_install_script("http://h:8000", 1, "c")


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
    monkeypatch.setattr(settings, "allow_insecure_install", False)
    assert "ALLOW_INSECURE:-1" not in build_install_script("http://h:8000", 1, "c")


@pytest.mark.asyncio
async def test_enrollment_reports_agent_version_and_sha256(client, db, admin_token):
    import hashlib
    from app.services.agent_deployer import LATEST_AGENT_VERSION

    device = Device(ip="192.168.1.92", display_name="Pi", is_online=True)
    db.add(device)
    await db.commit()

    client.cookies.set("gravitylan_token", session_store.create_session(user_agent=None))
    res = await client.post(f"/api/agent/enroll/{device.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["agent_version"] == LATEST_AGENT_VERSION
    dl = await client.get("/api/agent/download/agent")
    assert dl.status_code == 200
    assert body["agent_sha256"] == hashlib.sha256(dl.content).hexdigest()


def test_install_script_embeds_and_checks_sha256_before_config_download():
    from app.services.agent_deployer import LATEST_AGENT_VERSION, get_agent_script_sha256

    script = build_install_script("https://gravity.example", 3, "abc")
    expected_sha = get_agent_script_sha256()
    assert f"AGENT_VERSION={LATEST_AGENT_VERSION}\n" in script
    assert f"AGENT_SHA256={expected_sha}\n" in script
    assert 'echo "Agent SHA-256: $AGENT_SHA256"' in script
    assert script.index("SHA-256 checksum mismatch") < script.index("/api/agent/download/config/")


def _run_as_root_with_agent_download(script: str, tmp_path, agent_bytes: bytes) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    id_stub = bin_dir / "id"
    id_stub.write_text("#!/bin/sh\necho 0\n", newline="\n")
    id_stub.chmod(0o755)
    payload = tmp_path / "payload.py"
    payload.write_bytes(agent_bytes)
    curl = bin_dir / "curl"
    curl.write_text(
        '#!/bin/sh\n'
        f'echo "$@" >> "{(tmp_path / "curl.log").as_posix()}"\n'
        'out=""\n'
        'url=""\n'
        'while [ $# -gt 0 ]; do\n'
        '  if [ "$1" = "-o" ]; then out="$2"; shift 2; else url="$1"; shift; fi\n'
        'done\n'
        'case "$url" in\n'
        f'  */download/agent) cp "{payload.as_posix()}" "$out"; exit 0 ;;\n'
        '  *) exit 1 ;;\n'
        'esac\n',
        newline="\n",
    )
    curl.chmod(0o755)
    run_env = {**os.environ, "PATH": f"{bin_dir.as_posix()}{os.pathsep}{os.environ.get('PATH', '')}"}
    return subprocess.run([BASH, "-s"], input=script, env=run_env, capture_output=True, text=True, timeout=30)


@needs_bash
def test_install_script_aborts_on_checksum_mismatch_before_redeeming_code(tmp_path):
    script = build_install_script("https://gravity.example", 3, "abc", agent_version="0.2.5", agent_sha256="0" * 64)
    result = _run_as_root_with_agent_download(script, tmp_path, b"print('tampered')\n")
    assert result.returncode == 1
    assert "SHA-256 checksum mismatch" in result.stderr
    assert "/download/config/" not in (tmp_path / "curl.log").read_text()


@needs_bash
def test_install_script_verifies_checksum_when_bytes_match(tmp_path):
    import hashlib

    agent_bytes = b"print('authentic')\n"
    expected_sha = hashlib.sha256(agent_bytes).hexdigest()
    script = build_install_script("https://gravity.example", 3, "abc", agent_version="0.2.5", agent_sha256=expected_sha)
    result = _run_as_root_with_agent_download(script, tmp_path, agent_bytes)
    assert "GravityLAN Agent Installer (v0.2.5)" in result.stdout
    assert f"SHA-256 verified ({expected_sha})" in result.stdout
    assert "SHA-256 checksum mismatch" not in result.stderr
    assert "/download/config/" in (tmp_path / "curl.log").read_text()
