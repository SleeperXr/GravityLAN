"""SSH-based agent deployment service.

Connects to a remote Linux host, copies the GravityLAN Agent script,
generates a config file with a unique token, creates a systemd service,
and starts the agent. SSH credentials are never stored.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from app.services.ssh_utils import (
    RemoteRunner,
    build_connect_kwargs,
    build_ssh_client,
    connect_with_gateway_fallback,
)

logger = logging.getLogger(__name__)


def get_agent_script_path() -> Path:
    """Find the agent script in various possible locations."""
    # 1. Absolute path in Docker
    p = Path("/app/agent/gravitylan-agent.py")
    if p.exists():
        return p

    # 2. Relative to this file (backend/app/services/agent_deployer.py)
    # Target: agent/gravitylan-agent.py
    this_file = Path(__file__).resolve()

    # Try parents (up to 4 levels)
    curr = this_file.parent
    for _ in range(4):
        candidate = curr / "agent" / "gravitylan-agent.py"
        if candidate.exists():
            return candidate

        candidate = curr / "gravitylan-agent.py"  # In case it's in the same dir
        if candidate.exists():
            return candidate

        curr = curr.parent

    # 3. Fallback to CWD
    p = Path("agent/gravitylan-agent.py").resolve()
    if p.exists():
        return p

    return Path("/app/agent/gravitylan-agent.py")  # Default


AGENT_SCRIPT_PATH = get_agent_script_path()
logger.info(f"Agent script path resolved to: {AGENT_SCRIPT_PATH} (Exists: {AGENT_SCRIPT_PATH.exists()})")

SERVICE_UNIT_PATH = AGENT_SCRIPT_PATH.parent / "gravitylan-agent.service"


def _parse_version_line(line: str) -> str | None:
    """Extract version from a VERSION = 'x.y.z' line."""
    parts = line.split("=", 1)
    if len(parts) == 2:
        return parts[1].strip().strip('"').strip("'")
    return None


def get_latest_agent_version() -> str:
    """Reads the agent version from the local gravitylan-agent.py file."""
    if not AGENT_SCRIPT_PATH.exists():
        return "0.2.5"

    try:
        with open(AGENT_SCRIPT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("VERSION ="):
                    version = _parse_version_line(line)
                    if version:
                        return version
    except Exception as e:
        logger.error("Failed to parse agent version from file: %s", e)

    return "0.2.5"  # Fallback


LATEST_AGENT_VERSION = get_latest_agent_version()

# Standardized path matching manual install script
REMOTE_BASE_DIR = "/opt/gravitylan-agent"
REMOTE_AGENT_PATH = f"{REMOTE_BASE_DIR}/gravitylan-agent.py"
REMOTE_CONFIG_PATH = f"{REMOTE_BASE_DIR}/agent.conf"
REMOTE_SERVICE_PATH = "/etc/systemd/system/gravitylan-agent.service"


async def _probe_python(client) -> str:
    """Detect available python3 binary on remote host."""
    try:
        _, stdout, _ = client.exec_command("which python3")
        if stdout.channel.recv_exit_status() == 0:
            return stdout.read().decode().strip()
    except Exception:
        pass
    return "python3"


async def _probe_platform(client, host_ip: str) -> tuple[bool, bool]:
    """Detect systemd and Synology rc.d availability."""
    _, stdout, _ = client.exec_command("test -d /run/systemd/system && echo 'systemd'", timeout=5)
    has_systemd = stdout.read().decode().strip() == "systemd"

    _, stdout, _ = client.exec_command("test -f /etc/synoinfo.conf && echo 'synology'", timeout=5)
    has_syno_rc = stdout.read().decode().strip() == "synology"

    logger.info("Platform detection for %s: systemd=%s, synology_rc=%s", host_ip, has_systemd, has_syno_rc)
    return has_systemd, has_syno_rc


def _build_cleanup_script(has_systemd: bool, has_syno_rc: bool) -> list[str]:
    """Build pre-install cleanup command list."""
    cmds = [
        "systemctl stop gravitylan-agent.service homelan-agent.service agent.service || true",
        "systemctl disable gravitylan-agent.service homelan-agent.service agent.service || true",
        "pkill -9 -f 'agent.py|homelan-agent.py|gravitylan-agent.py' || true",
        "rm -rf /opt/homelan /opt/gravitylan /opt/gravitylan-agent /root/gravitylan-agent /usr/local/homelan /usr/local/gravitylan-agent",
        "rm -f /etc/systemd/system/gravitylan-agent.service /etc/systemd/system/homelan-agent.service",
    ]
    if has_systemd:
        cmds.append("systemctl daemon-reload || true")
    return cmds


def _is_ssh_connected(client) -> bool:
    """Return True when the SSH transport is still alive."""
    return bool(client and client.get_transport() and client.get_transport().is_active())


def _map_ssh_error(exc: Exception, host_ip: str) -> tuple[bool, str] | None:
    """Map a paramiko exception to a user-friendly message.

    Returns ``(False, message)`` for recognized errors, or ``None`` when the
    exception is not SSH-related (caller should log + fall back).
    """
    import paramiko
    from app.config import settings

    if isinstance(exc, paramiko.ssh_exception.BadHostKeyException):
        msg = f"SSH Host Key verification failed: The host key presented by {host_ip} does not match the stored key in known_hosts."
        if settings.ssh_strict_mode:
            msg += " (SSH Strict Mode is active. Update the known_hosts file inside the server container to match the host key.)"
        return False, msg
    if isinstance(exc, paramiko.ssh_exception.SSHException):
        err_str = str(exc)
        if "not found in known_hosts" in err_str:
            msg = f"SSH connection rejected: Unknown host key for {host_ip}."
            if settings.ssh_strict_mode:
                msg += " (SSH Strict Mode is active. You must pre-register the host key in the server's known_hosts file, or disable GRAVITYLAN_SSH_STRICT_MODE.)"
            return False, msg
        return False, "SSH connection failed. Please check host availability and port."
    if isinstance(exc, paramiko.AuthenticationException):
        return False, "SSH authentication failed. Please check your credentials."
    return None


def _check_sudo(client) -> bool:
    """Return True when the remote user can invoke sudo."""
    _, stdout, _ = client.exec_command("which sudo", timeout=5)
    return stdout.channel.recv_exit_status() == 0


def _stage_file(client, tmp_path: str, content: str) -> None:
    """Write content to a remote temp file via heredoc."""
    from app.services.ssh_utils import _exec_impl
    _exec_impl(client, f"cat > {tmp_path} << 'GRAVITYLAN_EOF'\n{content}\nGRAVITYLAN_EOF", 15, None)


def _install_systemd_service(
    runner: RemoteRunner,
    client,
    device_id: int,
    python_path: str,
    remote_agent_path: str,
    base_dir: str,
) -> bool:
    """Write and install systemd unit, return True on success."""
    unit = _generate_service_unit(python_path, remote_agent_path, base_dir)
    tmp_service = f"/tmp/gravitylan_service_{device_id}.service"

    _stage_file(client, tmp_service, unit)

    service_cmds = [
        f"rm -f {REMOTE_SERVICE_PATH} || true",
        f"cp {tmp_service} {REMOTE_SERVICE_PATH}",
        f"rm -f {tmp_service} || true",
        f"chmod 644 {REMOTE_SERVICE_PATH} || true",
        "systemctl daemon-reload || true",
        "systemctl enable gravitylan-agent || true",
        "systemctl restart gravitylan-agent || true",
    ]

    try:
        runner.run_sudo_batch(service_cmds)
        return True
    except Exception as e:
        logger.warning("Failed to install systemd service (%s). Will fallback to nohup.", e)
        return False


def _install_syno_rc(
    runner: RemoteRunner,
    client,
    device_id: int,
    python_path: str,
    remote_agent_path: str,
) -> None:
    """Install Synology rc.d startup script."""
    rc_script_path = "/usr/local/etc/rc.d/S99gravitylan-agent.sh"
    rc_content = f"""#!/bin/sh
# GravityLAN Agent Start Script for Synology

case "$1" in
    start)
        {python_path} {remote_agent_path} &
        ;;
    stop)
        pkill -f {remote_agent_path}
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    *)
        echo "Usage: $0 {{start|stop|restart}}"
        exit 1
esac
exit 0
"""
    tmp_rc = f"/tmp/gravitylan_rc_{device_id}.sh"
    _stage_file(client, tmp_rc, rc_content)

    rc_setup_cmds = [
        f"rm -f {rc_script_path} || true",
        f"cp {tmp_rc} {rc_script_path}",
        f"rm -f {tmp_rc} || true",
        f"chmod +x {rc_script_path} || true",
        f"{rc_script_path} restart || true",
    ]
    runner.run_sudo_batch(rc_setup_cmds)
    logger.info("Synology rc.d script deployed to %s", rc_script_path)


def _build_agent_config(server_url: str, token: str, device_id: int) -> str:
    """Generate agent configuration JSON."""
    config = {
        "server_url": server_url,
        "token": token,
        "device_id": device_id,
        "interval": 30,
        "disk_paths": ["/"],
        "enable_temp": True,
    }
    return json.dumps(config, indent=2)


def _is_agent_running(client, remote_agent_path: str) -> bool:
    """Check if agent process is running via ps."""
    _, stdout, _ = client.exec_command(f"ps aux | grep -v grep | grep {remote_agent_path}")
    return stdout.read().decode().strip() != ""


async def _nohup_fallback(
    client,
    host_ip: str,
    base_dir: str,
    python_path: str,
    remote_agent_path: str,
    server_url: str,
    token: str,
) -> tuple[bool, str]:
    """Last-resort nohup start; return (success, message)."""
    logger.info("Agent not running via service. Falling back to nohup...")

    client.exec_command(f"rm -f {base_dir}/gravitylan-agent.log || true")
    client.exec_command(f"pkill -f {remote_agent_path} || true")
    client.exec_command(f"cd {base_dir} && nohup {python_path} {remote_agent_path} > {base_dir}/gravitylan-agent.log 2>&1 &")

    await asyncio.sleep(3)

    if _is_agent_running(client, remote_agent_path):
        msg = f"Agent started (Nohup fallback, URL: {server_url})"
        _, stdout, _ = client.exec_command("test -f /etc/unraid-version && echo 'unraid'")
        if stdout.read().decode().strip() == "unraid":
            msg += ". NOTE: On Unraid, add the command to /boot/config/go for persistence."
        return True, msg

    _, stdout, _ = client.exec_command(f"tail -n 20 {base_dir}/gravitylan-agent.log")
    log_content = stdout.read().decode().strip()

    error_msg = "Agent could not be started (service start and nohup fallback both failed)."
    if log_content:
        logger.error("Agent startup log for %s:\n%s", host_ip, log_content)
        error_msg += " Check the server log or the agent's local log file for details."

    return False, error_msg


async def deploy_agent(
    *,
    host_ip: str,
    ssh_user: str,
    ssh_password: str | None = None,
    ssh_key: str | None = None,
    ssh_port: int = 22,
    server_url: str,
    device_id: int,
) -> tuple[bool, str, str]:
    """Deploy and start the GravityLAN agent on a remote Linux host.

    Returns:
        (success, message, token)
    """
    token = uuid.uuid4().hex
    base_dir = REMOTE_BASE_DIR
    cleanup_msg = ""

    client = build_ssh_client()

    try:
        connect_kwargs, err = build_connect_kwargs(host_ip, ssh_user, ssh_port, ssh_password, ssh_key)
        if err:
            return False, err, ""

        await connect_with_gateway_fallback(client, connect_kwargs, host_ip)

        # Check sudo availability
        has_sudo = _check_sudo(client)

        runner = RemoteRunner(client, has_sudo, ssh_user, ssh_password)

        # Pre-install cleanup
        has_systemd, has_syno_rc = await _probe_platform(client, host_ip)
        cleanup_cmds = _build_cleanup_script(has_systemd, has_syno_rc)
        runner.run_sudo_batch(cleanup_cmds)

        # Ensure base directory
        runner.run(f"mkdir -p {base_dir}")

        # Deploy agent script
        with open(AGENT_SCRIPT_PATH, "r", encoding="utf-8") as f:
            agent_content = f.read()

        tmp_agent = f"/tmp/gravitylan_agent_{device_id}.py"
        _stage_file(client, tmp_agent, agent_content)
        runner.run(f"mv {tmp_agent} {REMOTE_AGENT_PATH} && chmod +x {REMOTE_AGENT_PATH}")
        logger.info("Agent script deployed to %s", REMOTE_AGENT_PATH)

        # Deploy config
        config_json = _build_agent_config(server_url, token, device_id)
        tmp_config = f"/tmp/gravitylan_config_{device_id}.json"
        _stage_file(client, tmp_config, config_json)
        runner.run(f"cp {tmp_config} {REMOTE_CONFIG_PATH} && rm -f {tmp_config} && chmod 644 {REMOTE_CONFIG_PATH}")
        logger.info("Agent config deployed to %s", REMOTE_CONFIG_PATH)

        # Install service
        python_path = await _probe_python(client)

        if has_systemd:
            success = _install_systemd_service(runner, client, device_id, python_path, REMOTE_AGENT_PATH, base_dir)
            if not success:
                has_systemd = False
        elif has_syno_rc:
            _install_syno_rc(runner, client, device_id, python_path, REMOTE_AGENT_PATH)

        # Verification
        await asyncio.sleep(2)

        if _is_agent_running(client, REMOTE_AGENT_PATH):
            return True, f"Agent started successfully{cleanup_msg} (Directory: {base_dir}, URL: {server_url})", token

        # Nohup fallback
        return await _nohup_fallback(client, host_ip, base_dir, python_path, REMOTE_AGENT_PATH, server_url, token)

    except Exception as exc:
        mapped = _map_ssh_error(exc, host_ip)
        if mapped is not None:
            return mapped[0], mapped[1], ""

        logger.exception("Agent deployment failed")
        return False, "Deployment failed due to an unexpected internal error.", ""
    finally:
        client.close()
        logger.info("SSH connection closed. Credentials discarded.")


async def remove_agent(
    *,
    host_ip: str,
    ssh_user: str,
    ssh_password: str | None = None,
    ssh_key: str | None = None,
    ssh_port: int = 22,
) -> tuple[bool, str]:
    """Uninstall the GravityLAN Agent from a remote Linux host.

    Performs:
    1. Stop and disable systemd service (if exists).
    2. Kill any running nohup processes.
    3. Delete /etc/systemd/system/gravitylan-agent.service.
    4. Delete installation directory.
    """
    client = build_ssh_client()

    try:
        connect_kwargs, err = build_connect_kwargs(host_ip, ssh_user, ssh_port, ssh_password, ssh_key)
        if err:
            return False, err

        await connect_with_gateway_fallback(client, connect_kwargs, host_ip)

        # Check for sudo
        has_sudo = _check_sudo(client)

        runner = RemoteRunner(client, has_sudo, ssh_user, ssh_password)

        # Scorched earth cleanup
        cleanup_commands = _build_cleanup_script(has_systemd=True, has_syno_rc=False)
        runner.run_sudo_batch(cleanup_commands)

        return True, "Agent has been completely removed and all processes stopped."

    except Exception as exc:
        mapped = _map_ssh_error(exc, host_ip)
        if mapped is not None:
            return mapped

        logger.exception("Agent removal failed")
        return False, "Deinstallation failed due to an unexpected internal error."
    finally:
        client.close()


def _generate_service_unit(python_path: str = "python3", agent_path: str = "/opt/gravitylan/gravitylan-agent.py", working_dir: str = "/opt/gravitylan") -> str:
    """Generate a systemd unit file string as fallback.

    Returns:
        Complete systemd service unit as a string.
    """
    return f"""[Unit]
Description=GravityLAN System Monitor Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={python_path} {agent_path}
WorkingDirectory={working_dir}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=gravitylan-agent

[Install]
WantedBy=multi-user.target
"""