"""SSH-based service for listing and applying package updates on Linux agents.

Reuses connection logic and warning policy from agent_deployer.py for robustness.
"""

from __future__ import annotations

import asyncio
import logging
import re
import io
import uuid
import paramiko
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from app.config import settings
from app.services.agent_deployer import CustomWarningPolicy, _load_ssh_key

logger = logging.getLogger(__name__)

async def run_ssh_command_stream(
    *,
    host_ip: str,
    ssh_user: str,
    ssh_password: str | None = None,
    ssh_key: str | None = None,
    ssh_port: int = 22,
    command: str,
    output_callback: Callable[[str], None]
) -> tuple[bool, str]:
    """Connects to host and executes command, streaming stdout/stderr line-by-line."""
    client = paramiko.SSHClient()
    if settings.ssh_strict_mode:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(CustomWarningPolicy())

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
                return False, f"Invalid SSH key format: {e}"
        elif ssh_password:
            connect_kwargs["password"] = ssh_password
        else:
            return False, "Neither password nor SSH key provided."

        # Connection logic with Macvlan/Docker isolation fallback
        try:
            client.connect(**connect_kwargs)
        except Exception as e:
            from app.services.docker_service import docker_service
            gateway = docker_service.get_bridge_gateway()
            if gateway and host_ip != gateway:
                logger.info("Direct patch connection failed (%s). Trying Host Bypass gateway: %s", e, gateway)
                connect_kwargs["hostname"] = gateway
                client.connect(**connect_kwargs)
            else:
                raise e

        # Set up shell channel or execute command
        transport = client.get_transport()
        if not transport:
            return False, "Failed to get SSH transport channel."

        channel = transport.open_session()
        channel.get_pty()  # request pty to get combined output and avoid buffering issues
        
        # Check sudo usage
        needs_sudo = ssh_user != "root"
        if needs_sudo:
            # We want to run command as sudo. Since we have a PTY, sudo will prompt for password
            # if required.
            run_cmd = f"sudo -S {command}"
        else:
            run_cmd = command

        channel.exec_command(run_cmd)

        # Buffer to read output line by line
        loop = asyncio.get_running_loop()
        
        # Wait for pwd prompt if sudo and password is provided
        if needs_sudo and ssh_password:
            # Sudo password input handler
            await asyncio.sleep(0.5)
            if channel.send_ready():
                # Check if it asks for password
                if channel.recv_ready():
                    buf = channel.recv(1024).decode("utf-8", errors="replace")
                    if "password" in buf.lower() or "[sudo]" in buf.lower():
                        channel.send(f"{ssh_password}\n")
        
        while True:
            # Check if there is data to read
            if channel.recv_ready():
                # Read chunks
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                if not chunk:
                    break
                # Stream the output
                output_callback(chunk)
            elif channel.exit_status_ready():
                # Exit once finished and no data remains
                if not channel.recv_ready():
                    break
            await asyncio.sleep(0.1)

        exit_code = channel.get_exit_status()
        if exit_code == 0:
            return True, "Success"
        else:
            return False, f"Command exited with code {exit_code}"

    except Exception as e:
        logger.error("SSH command execution error: %s", e)
        return False, str(e)
    finally:
        client.close()

async def list_device_updates(
    *,
    host_ip: str,
    ssh_user: str,
    ssh_password: str | None = None,
    ssh_key: str | None = None,
    ssh_port: int = 22,
) -> dict[str, Any]:
    """Queries package updates lists over SSH (Debian/Ubuntu/Fedora/CentOS)."""
    client = paramiko.SSHClient()
    if settings.ssh_strict_mode:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(CustomWarningPolicy())

    try:
        connect_kwargs: dict = {
            "hostname": host_ip,
            "port": ssh_port,
            "username": ssh_user,
            "timeout": 15,
        }
        if ssh_key:
            connect_kwargs["pkey"] = _load_ssh_key(ssh_key)
        elif ssh_password:
            connect_kwargs["password"] = ssh_password

        try:
            client.connect(**connect_kwargs)
        except Exception as e:
            from app.services.docker_service import docker_service
            gateway = docker_service.get_bridge_gateway()
            if gateway and host_ip != gateway:
                connect_kwargs["hostname"] = gateway
                client.connect(**connect_kwargs)
            else:
                raise e

        # 1. Detect Package Manager
        _, stdout, _ = client.exec_command("which apt-get || which dnf || which yum", timeout=10)
        pkg_manager_path = stdout.read().decode().strip()
        
        result = {
            "patch_manager": None,
            "packages": [],
            "major_upgrade_available": None
        }

        if "apt-get" in pkg_manager_path:
            result["patch_manager"] = "apt"
            # Refresh package cache first (requires sudo/root)
            needs_sudo = ssh_user != "root"
            update_cmd = "sudo -S apt-get update" if needs_sudo else "apt-get update"
            
            # Execute update
            chan = client.get_transport().open_session()
            if needs_sudo:
                chan.get_pty()
            chan.exec_command(update_cmd)
            if needs_sudo and ssh_password:
                await asyncio.sleep(0.5)
                if chan.send_ready():
                    chan.send(f"{ssh_password}\n")
            # Wait for update to complete
            while not chan.exit_status_ready():
                await asyncio.sleep(0.1)

            # Query upgradable packages
            _, stdout, _ = client.exec_command("apt list --upgradable 2>/dev/null", timeout=15)
            output = stdout.read().decode("utf-8")
            
            # Parse apt list --upgradable output. Format:
            # package/suite version arch [upgradable from: old_version]
            # e.g., curl/jammy-updates 7.81.0-1ubuntu1.16 amd64 [upgradable from: 7.81.0-1ubuntu1.15]
            for line in output.splitlines():
                if "upgradable from" in line:
                    match = re.match(r"^([^/]+)/([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+\[upgradable from:\s+([^\]]+)\]", line)
                    if match:
                        pkg_name, suite, new_ver, arch, old_ver = match.groups()
                        result["packages"].append({
                            "package": pkg_name,
                            "current_version": old_ver,
                            "new_version": new_ver,
                            "repo": suite
                        })

            # Check major upgrade (Ubuntu only)
            _, stdout, _ = client.exec_command("which do-release-upgrade", timeout=5)
            if stdout.read().decode().strip():
                _, stdout, _ = client.exec_command("do-release-upgrade -c", timeout=10)
                out_upgrade = stdout.read().decode("utf-8")
                for line in out_upgrade.splitlines():
                    if "New release" in line and "available" in line:
                        parts = line.split("'")
                        if len(parts) >= 3:
                            result["major_upgrade_available"] = parts[1]

        elif "dnf" in pkg_manager_path:
            result["patch_manager"] = "dnf"
            # Get list of upgrades
            _, stdout, _ = client.exec_command("dnf check-update --quiet", timeout=20)
            output = stdout.read().decode("utf-8")
            
            # Parse dnf check-update output. Lines look like:
            # curl.x86_64               7.81.0-1.fc39             updates
            # Let's get installed versions of those packages to populate current_version
            upgrades = []
            pkg_names = []
            for line in output.splitlines():
                parts = line.split()
                if len(parts) >= 3 and not line.startswith("Last metadata"):
                    # parts: [package_name.arch, new_version, repo]
                    pkg_and_arch = parts[0]
                    pkg_name = pkg_and_arch.rsplit(".", 1)[0]
                    upgrades.append({
                        "package": pkg_name,
                        "new_version": parts[1],
                        "repo": parts[2],
                        "current_version": "Installed" # Default fallback
                    })
                    pkg_names.append(pkg_name)

            # Optimisation: fetch current versions in a batch if there are upgrades
            if pkg_names:
                batch_cmd = f"rpm -q --qf '%{{NAME}} %{{VERSION}}-%{{RELEASE}}\\n' {' '.join(pkg_names[:100])}"
                _, stdout_rpm, _ = client.exec_command(batch_cmd, timeout=10)
                rpm_output = stdout_rpm.read().decode("utf-8")
                version_map = {}
                for line in rpm_output.splitlines():
                    subparts = line.split()
                    if len(subparts) == 2:
                        version_map[subparts[0]] = subparts[1]
                
                for item in upgrades:
                    if item["package"] in version_map:
                        item["current_version"] = version_map[item["package"]]
            
            result["packages"] = upgrades

        elif "yum" in pkg_manager_path:
            result["patch_manager"] = "yum"
            _, stdout, _ = client.exec_command("yum check-update --quiet", timeout=20)
            output = stdout.read().decode("utf-8")
            
            upgrades = []
            for line in output.splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    pkg_and_arch = parts[0]
                    pkg_name = pkg_and_arch.rsplit(".", 1)[0]
                    upgrades.append({
                        "package": pkg_name,
                        "new_version": parts[1],
                        "repo": parts[2],
                        "current_version": "Installed"
                    })
            result["packages"] = upgrades

        return result

    except Exception as e:
        logger.error("Failed to query package updates over SSH: %s", e)
        return {"patch_manager": None, "packages": [], "major_upgrade_available": None, "error": str(e)}
    finally:
        client.close()
