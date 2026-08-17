"""SSH-based agent deployment service.

Connects to a remote Linux host, copies the GravityLAN Agent script,
generates a config file with a unique token, creates a systemd service,
and starts the agent. SSH credentials are never stored.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import uuid
from pathlib import Path

import paramiko

logger = logging.getLogger(__name__)


class CustomWarningPolicy(paramiko.WarningPolicy):
    """Custom warning policy for missing host keys to satisfy CodeQL static analysis."""
    pass


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


def _load_ssh_key(ssh_key: str):
    """Try to load an SSH private key from a string using various formats.

    Supports RSA, Ed25519, ECDSA, and DSS. Detects PuTTY keys to provide better errors.
    """
    # Check for PuTTY keys which paramiko doesn't support
    if "PuTTY-User-Key-File" in ssh_key:
        raise ValueError(
            "PuTTY-Key (.ppk) detected. Please convert the key using PuTTYgen "
            "(Export -> Export OpenSSH key) or use a password instead."
        )

    key_types = [
        paramiko.RSAKey,
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
        paramiko.DSSKey
    ]

    errors = []
    for key_cls in key_types:
        try:
            return key_cls.from_private_key(io.StringIO(ssh_key))
        except Exception as e:
            errors.append(f"{key_cls.__name__}: {str(e)}")
            continue

    raise ValueError(f"Invalid key format or encrypted key (passphrase not supported). Details: {'; '.join(errors)}")


def _build_ssh_client() -> paramiko.SSHClient:
    """Create an SSH client with host key policy based on settings."""
    from app.config import settings
    client = paramiko.SSHClient()
    if settings.ssh_strict_mode:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(CustomWarningPolicy())
    return client


def _build_connect_kwargs(
    host_ip: str,
    ssh_user: str,
    ssh_port: int,
    ssh_password: str | None,
    ssh_key: str | None,
) -> tuple[dict, str | None]:
    """Build connection kwargs for paramiko client.connect.

    Returns:
        (connect_kwargs, error_message_or_None)
    """
    connect_kwargs: dict = {
        "hostname": host_ip,
        "port": ssh_port,
        "username": ssh_user,
        "timeout": 15,
    }

    if ssh_key:
        try:
            connect_kwargs["pkey"] = _load_ssh_key(ssh_key)
        except ValueError as e:
            logger.error("SSH private key loading failed: %s", e)
            return {}, "Invalid SSH key format or encrypted key."
    elif ssh_password:
        connect_kwargs["password"] = ssh_password
    else:
        return {}, "Neither password nor SSH key provided."

    return connect_kwargs, None


async def _connect_with_gateway_fallback(
    client: paramiko.SSHClient,
    connect_kwargs: dict,
    host_ip: str,
) -> None:
    """Attempt SSH connection with Docker bridge gateway fallback."""
    try:
        client.connect(**connect_kwargs)
        return
    except Exception as e:
        from app.services.docker_service import docker_service
        gateway = docker_service.get_bridge_gateway()
        if not gateway or host_ip == gateway:
            raise e

    logger.info("Direct connection failed. Attempting Host Bypass via bridge gateway: %s", gateway)
    connect_kwargs["hostname"] = gateway
    client.connect(**connect_kwargs)


class _RemoteRunner:
    """Executes commands on a remote host via paramiko, handling sudo and timeouts."""

    def __init__(self, client: paramiko.SSHClient, has_sudo: bool, ssh_user: str, ssh_password: str | None):
        self._client = client
        self._has_sudo = has_sudo
        self._ssh_user = ssh_user
        self._ssh_password = ssh_password

    @property
    def _needs_sudo_wrap(self) -> bool:
        return self._has_sudo and self._ssh_user != "root"

    @property
    def _sudo_password(self) -> str | None:
        return self._ssh_password if self._needs_sudo_wrap else None

    def run(self, command: str, timeout: int = 15) -> str:
        """Execute a single command, raising on non-zero exit (except benign 1 for 'not found')."""
        if self._needs_sudo_wrap and "sudo -S" not in command:
            command = f"sudo -S bash << 'GRAVITYLAN_SUDO_EOF'\n{command}\nGRAVITYLAN_SUDO_EOF"

        return _exec_impl(self._client, command, timeout, self._sudo_password)

    def run_batch(self, commands: list[str], timeout: int = 15) -> list[str]:
        """Execute multiple commands sequentially."""
        results = []
        for cmd in commands:
            results.append(self.run(cmd, timeout))
        return results

    def run_sudo_batch(self, commands: list[str], timeout: int = 15) -> str:
        """Execute multiple commands in a single sudo heredoc."""
        if not self._has_sudo or self._ssh_user == "root":
            return "\n".join(self.run(cmd, timeout) for cmd in commands)

        full_cmd = " && ".join(commands)
        heredoc = f"sudo -S bash << 'GRAVITYLAN_SUDO_EOF'\nset -e\n{full_cmd}\nGRAVITYLAN_SUDO_EOF"
        return _exec_impl(self._client, heredoc, timeout, self._ssh_password)


def _exec_impl(client: paramiko.SSHClient, command: str, timeout: int, sudo_pass: str | None) -> str:
    """Low-level command execution with sudo password support and timeout handling."""
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)

    if sudo_pass and "sudo -S" in command:
        stdin.write(f"{sudo_pass}\n")
        stdin.flush()

    start_time = time.time()
    while not stdout.channel.exit_status_ready():
        if time.time() - start_time > timeout:
            stdout.channel.close()
            raise RuntimeError(f"Command timed out after {timeout}s: {command}")
        time.sleep(0.1)

    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode(errors='ignore').strip()
    err = stderr.read().decode(errors='ignore').strip()

    if exit_code != 0:
        if exit_code == 1 and ("not found" in err or "no such" in err.lower()):
            return out
        logger.warning("Command '%s' failed (exit %d): %s", command, exit_code, err)
        raise RuntimeError(f"Command failed with exit code {exit_code}: {err or out}")

    return out


async def _probe_python(client: paramiko.SSHClient) -> str:
    """Detect available python3 binary on remote host."""
    try:
        _, stdout, _ = client.exec_command("which python3")
        if stdout.channel.recv_exit_status() == 0:
            return stdout.read().decode().strip()
    except Exception:
        pass
    return "python3"


async def _probe_platform(client: paramiko.SSHClient, host_ip: str) -> tuple[bool, bool]:
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


def _stage_file(client: paramiko.SSHClient, tmp_path: str, content: str) -> None:
    """Write content to a remote temp file via heredoc."""
    _exec_impl(client, f"cat > {tmp_path} << 'GRAVITYLAN_EOF'\n{content}\nGRAVITYLAN_EOF", 15, None)


def _install_systemd_service(
    runner: _RemoteRunner,
    client: paramiko.SSHClient,
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
    runner: _RemoteRunner,
    client: paramiko.SSHClient,
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


def _is_agent_running(client: paramiko.SSHClient, remote_agent_path: str) -> bool:
    """Check if agent process is running via ps."""
    _, stdout, _ = client.exec_command(f"ps aux | grep -v grep | grep {remote_agent_path}")
    return stdout.read().decode().strip() != ""


async def _nohup_fallback(
    client: paramiko.SSHClient,
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

    client = _build_ssh_client()

    try:
        connect_kwargs, err = _build_connect_kwargs(host_ip, ssh_user, ssh_port, ssh_password, ssh_key)
        if err:
            return False, err, ""

        await _connect_with_gateway_fallback(client, connect_kwargs, host_ip)

        # Check sudo availability
        _, stdout, _ = client.exec_command("which sudo", timeout=5)
        has_sudo = stdout.channel.recv_exit_status() == 0

        runner = _RemoteRunner(client, has_sudo, ssh_user, ssh_password)

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

    except paramiko.ssh_exception.BadHostKeyException as exc:
        msg = f"SSH Host Key verification failed: The host key presented by {host_ip} does not match the stored key in known_hosts."
        from app.config import settings
        if settings.ssh_strict_mode:
            msg += " (SSH Strict Mode is active. Update the known_hosts file inside the server container to match the host key.)"
        return False, msg, ""
    except paramiko.ssh_exception.SSHException as exc:
        err_str = str(exc)
        from app.config import settings
        if "not found in known_hosts" in err_str:
            msg = f"SSH connection rejected: Unknown host key for {host_ip}."
            if settings.ssh_strict_mode:
                msg += " (SSH Strict Mode is active. You must pre-register the host key in the server's known_hosts file, or disable GRAVITYLAN_SSH_STRICT_MODE.)"
            return False, msg, ""
        logger.error("SSH connection error for %s: %s", host_ip, exc)
        return False, "SSH connection failed. Please check host availability and port.", ""
    except paramiko.AuthenticationException:
        return False, "SSH authentication failed. Please check your credentials.", ""
    except Exception as exc:
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
    client = _build_ssh_client()

    try:
        connect_kwargs, err = _build_connect_kwargs(host_ip, ssh_user, ssh_port, ssh_password, ssh_key)
        if err:
            return False, err

        await _connect_with_gateway_fallback(client, connect_kwargs, host_ip)

        # Check for sudo
        _, stdout, _ = client.exec_command("which sudo", timeout=5)
        has_sudo = stdout.channel.recv_exit_status() == 0

        runner = _RemoteRunner(client, has_sudo, ssh_user, ssh_password)

        # Scorched earth cleanup
        cleanup_commands = [
            "systemctl stop gravitylan-agent.service homelan-agent.service agent.service || true",
            "systemctl disable gravitylan-agent.service homelan-agent.service agent.service || true",
            "pkill -9 -f 'agent.py|homelan-agent.py|gravitylan-agent.py' || true",
            "rm -rf /opt/homelan /opt/gravitylan /opt/gravitylan-agent /root/gravitylan-agent /usr/local/homelan /usr/local/gravitylan-agent",
            "rm -f /etc/systemd/system/gravitylan-agent.service /etc/systemd/system/homelan-agent.service",
            "systemctl daemon-reload || true",
        ]

        runner.run_sudo_batch(cleanup_commands)

        return True, "Agent has been completely removed and all processes stopped."

    except paramiko.ssh_exception.BadHostKeyException as exc:
        from app.config import settings
        msg = f"SSH Host Key verification failed: The host key presented by {host_ip} does not match the stored key in known_hosts."
        if settings.ssh_strict_mode:
            msg += " (SSH Strict Mode is active. Update the known_hosts file inside the server container to match the host key.)"
        return False, msg
    except paramiko.ssh_exception.SSHException as exc:
        from app.config import settings
        err_str = str(exc)
        if "not found in known_hosts" in err_str:
            msg = f"SSH connection rejected: Unknown host key for {host_ip}."
            if settings.ssh_strict_mode:
                msg += " (SSH Strict Mode is active. You must pre-register the host key in the server's known_hosts file, or disable GRAVITYLAN_SSH_STRICT_MODE.)"
            return False, msg
        logger.error("SSH connection error during agent removal on %s: %s", host_ip, exc)
        return False, "SSH connection failed."
    except paramiko.AuthenticationException:
        return False, "SSH authentication failed. Please check your credentials."
    except Exception as exc:
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