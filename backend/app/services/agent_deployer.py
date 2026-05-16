"""SSH-based agent deployment service.

Connects to a remote Linux host, copies the GravityLAN Agent script,
generates a config file with a unique token, creates a systemd service,
and starts the agent. SSH credentials are never stored.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import paramiko
import shlex

logger = logging.getLogger(__name__)

def get_agent_script_path() -> Path:
    """Find the agent script in various possible locations."""
    # 1. Absolute path in Docker
    p = Path("/app/agent/gravitylan-agent.py")
    if p.exists(): return p
    
    # 2. Relative to this file (backend/app/services/agent_deployer.py)
    # Target: agent/gravitylan-agent.py
    this_file = Path(__file__).resolve()
    
    # Try parents (up to 4 levels)
    curr = this_file.parent
    for _ in range(4):
        candidate = curr / "agent" / "gravitylan-agent.py"
        if candidate.exists(): return candidate
        
        candidate = curr / "gravitylan-agent.py" # In case it's in the same dir
        if candidate.exists(): return candidate
        
        curr = curr.parent
        
    # 3. Fallback to CWD
    p = Path("agent/gravitylan-agent.py").resolve()
    if p.exists(): return p
    
    return Path("/app/agent/gravitylan-agent.py") # Default

AGENT_SCRIPT_PATH = get_agent_script_path()
logger.info(f"Agent script path resolved to: {AGENT_SCRIPT_PATH} (Exists: {AGENT_SCRIPT_PATH.exists()})")

SERVICE_UNIT_PATH = AGENT_SCRIPT_PATH.parent / "gravitylan-agent.service"

# Standardized path matching manual install script
REMOTE_BASE_DIR = "/opt/gravitylan-agent"
REMOTE_AGENT_PATH = f"{REMOTE_BASE_DIR}/gravitylan-agent.py"
REMOTE_CONFIG_PATH = f"{REMOTE_BASE_DIR}/agent.conf"
REMOTE_SERVICE_PATH = "/etc/systemd/system/gravitylan-agent.service"


def _load_ssh_key(ssh_key: str):
    """Try to load an SSH private key from a string using various formats.
    
    Supports RSA, Ed25519, ECDSA, and DSS. Detects PuTTY keys to provide better errors.
    """
    import io
    
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
    """Deploy the GravityLAN Agent to a remote Linux host via SSH.

    Performs the following steps:
    1. Connect via SSH (password or key-based).
    2. Check Python 3 availability on the target.
    3. Create /opt/gravitylan-agent/ directory.
    4. Upload gravitylan-agent.py.
    5. Generate unique token and write agent.conf.
    6. Install and start systemd service.

    Args:
        host_ip: Target device IP address.
        ssh_user: SSH username.
        ssh_password: SSH password (mutually exclusive with ssh_key).
        ssh_key: SSH private key as string (mutually exclusive with ssh_password).
        ssh_port: SSH port number.
        server_url: GravityLAN server URL the agent should report to.
        device_id: Database ID of the device.

    Returns:
        Tuple of (success: bool, message: str, token: str).
        Token is empty on failure.
    """
    # Defensive protocol check
    if server_url and not server_url.startswith(("http://", "https://")):
        server_url = f"http://{server_url}"

    token = uuid.uuid4().hex
    client = paramiko.SSHClient()
    # SECURITY NOTE: WarningPolicy is used to log unknown hosts. 
    # TODO: Implement RejectPolicy + Manual UI Confirmation.
    client.set_missing_host_key_policy(paramiko.WarningPolicy())

    try:
        # --- Connect ---
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
                return False, str(e), ""
        elif ssh_password:
            connect_kwargs["password"] = ssh_password
        else:
            return False, "Neither password nor SSH key provided.", ""

        connect_kwargs["timeout"] = 15  # 15s timeout for connection
        
        logger.info("Connecting to %s@%s:%d ...", ssh_user, host_ip, ssh_port)
        try:
            client.connect(**connect_kwargs)
        except Exception as e:
            # FALLBACK for Unraid/Docker Macvlan isolation:
            # If we can't reach the host IP directly, try via the internal bridge gateway
            from app.services.docker_service import docker_service
            gateway = docker_service.get_bridge_gateway()
            if gateway and host_ip != gateway:
                logger.info("Direct connection failed (%s). Attempting Host Bypass via bridge gateway: %s", e, gateway)
                connect_kwargs["hostname"] = gateway
                try:
                    client.connect(**connect_kwargs)
                except Exception as fb_err:
                    logger.error("Host Bypass also failed: %s", fb_err)
                    raise e # Raise original error if fallback also fails
            else:
                raise e

        # --- Check Python 3 ---
        _, stdout, _ = client.exec_command("which python3 || which python", timeout=10)
        python_path = stdout.read().decode().strip()
        
        _, stdout, _ = client.exec_command(f"{python_path} --version", timeout=10)
        python_version = stdout.read().decode().strip()
        
        if not python_path or not python_version:
            return False, "Python 3 was not found on the target system.", ""
        
        logger.info("Target Python: %s (%s)", python_version, python_path)

        # --- Identify OS and Init System ---
        _, stdout, _ = client.exec_command("ls /etc/synoinfo.conf", timeout=5)
        is_synology = stdout.channel.recv_exit_status() == 0
        if is_synology:
            logger.info("Synology NAS detected on %s", host_ip)
            # Use a more accessible path on Synology if /opt is not available
            base_dir = "/usr/local/gravitylan-agent"
        else:
            base_dir = REMOTE_BASE_DIR

        _, stdout, _ = client.exec_command("which sudo", timeout=5)
        has_sudo = stdout.channel.recv_exit_status() == 0
        
        _, stdout, _ = client.exec_command("which systemctl")
        has_systemd = stdout.channel.recv_exit_status() == 0
        
        _, stdout, _ = client.exec_command("which rc-service")
        has_openrc = stdout.channel.recv_exit_status() == 0
        
        # Synology specific init check
        has_syno_rc = is_synology and not has_systemd
        
        # Securely pass password via stdin if needed, instead of shell echo injection
        needs_sudo_pass = has_sudo and ssh_user != "root" and ssh_password
        
        def run_cmd(cmd_list: list[str], use_sudo: bool = True):
            """Helper to run a list of commands as a single batched operation via a temp script."""
            if not cmd_list: return
            
            # Combine into a single script body
            # Remove any existing sudo prefixes from individual commands to avoid nesting
            clean_cmds = [cmd.replace("sudo -S ", "").replace("sudo ", "") for cmd in cmd_list]
            script_content = "set -e\n" + "\n".join(clean_cmds)
            
            # Use a unique temp file for this operation
            tmp_script = f"/tmp/gravitylan_task_{uuid.uuid4().hex[:8]}.sh"
            
            try:
                # 1. Upload the script content using cat (works without SFTP)
                # We use a heredoc here, but it's okay because cat doesn't need stdin for a password
                _exec(client, command=f"cat > {tmp_script} << 'GRAVITYLAN_TASK_EOF'\n{script_content}\nGRAVITYLAN_TASK_EOF")
                _exec(client, command=f"chmod +x {tmp_script}")
                
                # 2. Execute the script
                if use_sudo and needs_sudo_pass:
                    # Now sudo -S can read the password from stdin, 
                    # while bash reads the script from the file! No conflict.
                    full_cmd = f"sudo -S bash {tmp_script}"
                    return _exec(client, command=full_cmd, sudo_pass=ssh_password, timeout=30)
                elif use_sudo and has_sudo and ssh_user != "root":
                    full_cmd = f"sudo bash {tmp_script}"
                    return _exec(client, command=full_cmd, timeout=30)
                else:
                    return _exec(client, command=f"bash {tmp_script}", timeout=30)
            finally:
                # 3. Cleanup the temp script
                try:
                    _exec(client, command=f"rm -f {tmp_script}")
                except Exception:
                    pass
        
        # --- Cleanup stale processes and legacy services first (BATCHED) ---
        cleanup_msg = ""
        try:
            # Construct a single multi-line script for cleanup
            cleanup_script = []
            
            # 1. systemd services
            if has_systemd:
                legacy_services = ["homelan-agent.service", "agent.service", "gravitylan-agent.service"]
                for svc in legacy_services:
                    cleanup_script.append(f"if systemctl is-active {svc} --quiet; then echo 'Stopping {svc}'; systemctl stop {svc} && systemctl disable {svc} && rm -f /etc/systemd/system/{svc}; fi")
            
            # 2. Synology legacy scripts
            if has_syno_rc:
                legacy_rc = ["/usr/local/etc/rc.d/S99homelan-agent.sh", "/usr/local/etc/rc.d/S99gravitylan-agent.sh"]
                for rc in legacy_rc:
                    cleanup_script.append(f"if [ -f {rc} ]; then echo 'Stopping Synology script {rc}'; {rc} stop && rm -f {rc}; fi")

            # 3. Kill processes
            cleanup_script.append("pkill -9 -f 'agent.py|homelan-agent.py|gravitylan-agent.py' || true")
            
            # 4. Remove directories
            legacy_dirs = ["/opt/homelan", "/usr/local/homelan", "/opt/gravitylan", "/opt/gravitylan-agent", "/root/gravitylan-agent"]
            for ldir in legacy_dirs:
                cleanup_script.append(f"rm -rf {ldir} || true")
                
            # Execute combined cleanup script
            if cleanup_script:
                logger.info("Running cleanup sequence on %s...", host_ip)
                run_cmd(cleanup_script)

        except Exception as e:
            logger.warning("Cleanup of legacy components partially failed (often expected if components don't exist): %s", e)

        # --- Create directory with fallback ---
        try:
            # Combine mkdir, chmod and write test into one call
            setup_cmds = [
                f"mkdir -p {base_dir}",
                f"chmod 755 {base_dir}",
                f"touch {base_dir}/.test_write",
                f"rm {base_dir}/.test_write"
            ]
            run_cmd(setup_cmds)
        except Exception as e:
            # Fallback to home directory
            logger.info("Restricted %s (%s). Falling back to home directory...", base_dir, e)
            run_cmd(["mkdir -p ~/gravitylan-agent", "chmod 755 ~/gravitylan-agent"], use_sudo=False)
            base_dir = _exec(client, command="cd ~/gravitylan-agent && pwd")
        
        remote_agent_path = f"{base_dir}/gravitylan-agent.py"
        remote_config_path = f"{base_dir}/agent.conf"
        logger.info("Using deployment directory: %s", base_dir)

        # Upload agent script via cat (Avoid SFTP which is often disabled on NAS) ---
        if not AGENT_SCRIPT_PATH.exists():
            return False, f"Agent script not found: {AGENT_SCRIPT_PATH}", ""

        agent_content = AGENT_SCRIPT_PATH.read_text()

        # Use staging in /tmp first (BATCHED mv + chmod)
        tmp_agent = f"/tmp/gravitylan_agent_{device_id}.py"
        _exec(client, command=f"cat > {tmp_agent} << 'GRAVITYLAN_EOF'\n{agent_content}\nGRAVITYLAN_EOF")
        run_cmd([f"mv {tmp_agent} {remote_agent_path}", f"chmod +x {remote_agent_path}"])
        logger.info("Agent script deployed to %s", remote_agent_path)

        # --- Write config ---
        config = {
            "server_url": server_url,
            "token": token,
            "device_id": device_id,
            "interval": 30,
            "disk_paths": ["/"],
            "enable_temp": True,
        }
        config_json = json.dumps(config, indent=2)

        # Write via staging (BATCHED cp + rm + chmod)
        tmp_config = f"/tmp/gravitylan_config_{device_id}.json"
        _exec(client, command=f"cat > {tmp_config} << 'GRAVITYLAN_EOF'\n{config_json}\nGRAVITYLAN_EOF")
        run_cmd([f"cp {tmp_config} {remote_config_path}", f"rm -f {tmp_config}", f"chmod 644 {remote_config_path}"])
        logger.info("Agent config deployed to %s", remote_config_path)

        if has_systemd:
            tmp_service = f"/tmp/gravitylan_service_{device_id}.service"
            unit = _generate_service_unit(python_path, remote_agent_path, base_dir)
            _exec(client, command=f"cat > {tmp_service} << 'GRAVITYLAN_EOF'\n{unit}\nGRAVITYLAN_EOF")
            
            try:
                service_cmds = [
                    f"rm -f {REMOTE_SERVICE_PATH} || true",
                    f"cp {tmp_service} {REMOTE_SERVICE_PATH}",
                    f"rm -f {tmp_service} || true",
                    f"chmod 644 {REMOTE_SERVICE_PATH} || true",
                    "systemctl daemon-reload || true",
                    "systemctl enable gravitylan-agent || true",
                    "systemctl restart gravitylan-agent || true"
                ]
                run_cmd(service_cmds)
            except Exception as e:
                logger.warning("Failed to install systemd service (%s). Will fallback to nohup.", e)
                has_systemd = False
        elif has_syno_rc:
            # Synology legacy rc.d script
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
            _exec(client, command=f"cat > {tmp_rc} << 'GRAVITYLAN_EOF'\n{rc_content}\nGRAVITYLAN_EOF")
            rc_setup_cmds = [
                f"rm -f {rc_script_path} || true",
                f"cp {tmp_rc} {rc_script_path}",
                f"rm -f {tmp_rc} || true",
                f"chmod +x {rc_script_path} || true",
                f"{rc_script_path} restart || true"
            ]
            run_cmd(rc_setup_cmds)
            logger.info("Synology rc.d script deployed to %s", rc_script_path)
        
        # --- Final Verification & Last Resort Fallback ---
        # Give it a moment to stabilize
        import asyncio
        await asyncio.sleep(2)
        
        # Check if running (via ps)
        _, stdout, _ = client.exec_command(f"ps aux | grep -v grep | grep {remote_agent_path}")
        is_running = stdout.read().decode().strip() != ""
        if is_running:
            return True, f"Agent started successfully{cleanup_msg} (Directory: {base_dir}, URL: {server_url})", token

        # Fallback for Unraid / non-systemd / Restricted systems
        logger.info("Agent not running via service. Falling back to nohup...")
        # Clear old log if possible to get fresh errors
        client.exec_command(f"rm -f {base_dir}/gravitylan-agent.log || true")
        # Kill existing agent if running
        client.exec_command(f"pkill -f {remote_agent_path} || true")
        # Start new agent - cd to base dir so it finds config.json
        client.exec_command(f"cd {base_dir} && nohup {python_path} {remote_agent_path} > {base_dir}/gravitylan-agent.log 2>&1 &")
        
        await asyncio.sleep(3) # Give it more time
        
        # Final verify
        _, stdout, _ = client.exec_command(f"ps aux | grep -v grep | grep {remote_agent_path}")
        is_running = stdout.read().decode().strip() != ""
        
        if is_running:
            msg = f"Agent started (Nohup fallback, URL: {server_url})"
            # Check if it's Unraid
            _, stdout, _ = client.exec_command("test -f /etc/unraid-version && echo 'unraid'")
            if stdout.read().decode().strip() == "unraid":
                msg += ". NOTE: On Unraid, add the command to /boot/config/go for persistence."
            return True, msg, token
        
        # If still not running, get the log content
        _, stdout, _ = client.exec_command(f"tail -n 20 {base_dir}/gravitylan-agent.log")
        log_content = stdout.read().decode().strip()
        
        error_msg = "Agent could not be started (service start and nohup fallback both failed)."
        if log_content:
            error_msg += f"\nLast log entries:\n{log_content}"
            
        return False, error_msg, token

    except paramiko.AuthenticationException:
        return False, "SSH authentication failed. Please check your credentials.", ""
    except paramiko.SSHException as exc:
        return False, f"SSH connection error: {exc}", ""
    except Exception as exc:
        logger.exception("Agent deployment failed")
        return False, f"Deployment failed: {exc}", ""
    finally:
        client.close()
        # Credentials are local variables — garbage collected after return
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
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())

    try:
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
                return False, str(e)
        elif ssh_password:
            connect_kwargs["password"] = ssh_password
        else:
            return False, "Neither password nor SSH key provided."

        try:
            client.connect(**connect_kwargs)
        except Exception as e:
            from app.services.docker_service import docker_service
            gateway = docker_service.get_bridge_gateway()
            if gateway and host_ip != gateway:
                logger.info("Direct connection failed for removal. Attempting Host Bypass via bridge gateway: %s", gateway)
                connect_kwargs["hostname"] = gateway
                try:
                    client.connect(**connect_kwargs)
                except Exception:
                    raise e
            else:
                raise e

        # Check for sudo
        _, stdout, _ = client.exec_command("which sudo", timeout=5)
        has_sudo = stdout.channel.recv_exit_status() == 0
        
        # 1. Scorched earth cleanup
        cleanup_commands = [
            "systemctl stop gravitylan-agent.service homelan-agent.service agent.service || true",
            "systemctl disable gravitylan-agent.service homelan-agent.service agent.service || true",
            "pkill -9 -f 'agent.py|homelan-agent.py|gravitylan-agent.py' || true",
            "rm -rf /opt/homelan /opt/gravitylan /opt/gravitylan-agent /root/gravitylan-agent /usr/local/homelan /usr/local/gravitylan-agent",
            "rm -f /etc/systemd/system/gravitylan-agent.service /etc/systemd/system/homelan-agent.service",
            "systemctl daemon-reload || true"
        ]
        
        if has_sudo and ssh_user != "root":
            # Combine into a single sudo call
            full_cmd = f"sudo bash << 'GRAVITYLAN_SUDO_EOF'\nset -e\n{' && '.join(cleanup_commands)}\nGRAVITYLAN_SUDO_EOF"
            _exec(client, command=full_cmd, sudo_pass=ssh_password)
        else:
            for cmd in cleanup_commands:
                _exec(client, command=cmd)
        
        return True, "Agent has been completely removed and all processes stopped."

    except Exception as exc:
        logger.exception("Agent removal failed")
        return False, f"Deinstallation failed: {exc}"
    finally:
        client.close()


def _exec(client: paramiko.SSHClient, command: str, timeout: int = 15, sudo_pass: str = None) -> str:
    """Execute a remote command and return stdout, optionally passing a sudo password to stdin.
    
    Args:
        client: Active paramiko SSH client.
        command: Shell command to execute.
        timeout: Command timeout in seconds.
        sudo_pass: Optional password for sudo.

    Returns:
        Command stdout as string.

    Raises:
        RuntimeError: If the command exits with non-zero status.
    """
    # Increase timeout slightly to account for slow sudo responses
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    
    if sudo_pass and "sudo -S" in command:
        # Give sudo a moment to present the prompt if it's slow
        stdin.write(f"{sudo_pass}\n")
        stdin.flush()
        
    # recv_exit_status() can block. We use a more robust check with timeout.
    import time
    start_time = time.time()
    while not stdout.channel.exit_status_ready():
        if time.time() - start_time > timeout:
            # Cleanup channel on timeout
            stdout.channel.close()
            raise RuntimeError(f"Command timed out after {timeout}s: {command}")
        time.sleep(0.1)
        
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode(errors='ignore').strip()
    err = stderr.read().decode(errors='ignore').strip()

    if exit_code != 0:
        # Ignore common non-critical errors during cleanup
        if exit_code == 1 and ("not found" in err or "no such" in err.lower()):
            return out
            
        logger.warning("Command '%s' failed (exit %d): %s", command, exit_code, err)
        raise RuntimeError(f"Command failed with exit code {exit_code}: {err or out}")

    return out


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
