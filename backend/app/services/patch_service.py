"""SSH-based service for listing and applying package updates on Linux agents.

Reuses connection logic and warning policy from ssh_utils.py for robustness.
paramiko blocks (connect timeouts, exec_command, stdout.read()), so these calls run
in a worker thread via ``asyncio.to_thread`` instead of freezing the event loop.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import shlex
import time
import paramiko
from typing import Any, Awaitable, Callable

from app.config import settings
from app.services.ssh_utils import (
    CustomWarningPolicy,
    PinnedHostKey,
    TofuHostKeyPolicy,
    _load_ssh_key,
    build_pinned_ssh_client,
    host_bypass_gateway,
)

logger = logging.getLogger(__name__)

# Fixed sudo prompt (sudo -p) so it can be recognised regardless of the host's language
_SUDO_PROMPT = "SUDOPROMPT:"


def _build_client(
    pinned_host_key: PinnedHostKey | None = None,
    tofu_policy: TofuHostKeyPolicy | None = None,
) -> paramiko.SSHClient:
    """Create a hardened SSH client with the configured host-key policy."""
    if pinned_host_key is not None:
        return build_pinned_ssh_client(pinned_host_key)
    client = paramiko.SSHClient()
    if settings.ssh_strict_mode:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    elif tofu_policy is not None:
        client.set_missing_host_key_policy(tofu_policy)
    else:
        client.set_missing_host_key_policy(CustomWarningPolicy())
    return client


def _build_connect_kwargs(
    host_ip: str,
    ssh_user: str,
    ssh_port: int,
    ssh_password: str | None = None,
    ssh_key: str | None = None,
    ssh_key_passphrase: str | None = None,
) -> tuple[dict | None, str | None]:
    """Build paramiko connect kwargs; returns (kwargs, error_message)."""
    connect_kwargs: dict = {
        "hostname": host_ip,
        "port": ssh_port,
        "username": ssh_user,
        "timeout": 15,
    }
    if ssh_key:
        try:
            connect_kwargs["pkey"] = _load_ssh_key(ssh_key, ssh_key_passphrase)
        except Exception as e:
            return None, f"Invalid SSH key format: {e}"
    elif ssh_password:
        connect_kwargs["password"] = ssh_password
    else:
        return None, "Neither password nor SSH key provided."
    return connect_kwargs, None


def _connect_with_fallback(client: paramiko.SSHClient, connect_kwargs: dict, host_ip: str) -> None:
    """Connect directly; only the Docker host itself is retried on the bridge gateway (#46)."""
    try:
        client.connect(**connect_kwargs)
    except Exception as e:
        gateway = host_bypass_gateway(host_ip)
        if gateway:
            logger.info("Direct connection failed (%s). Trying Host Bypass gateway: %s", e, gateway)
            connect_kwargs["hostname"] = gateway
            client.connect(**connect_kwargs)
        else:
            raise e


def _open_command_channel(
    client: paramiko.SSHClient, connect_kwargs: dict, host_ip: str, run_cmd: str
) -> paramiko.Channel | None:
    """Connect and start ``run_cmd`` on a PTY channel; None without a transport.

    Blocks on the network (connect timeout, gateway fallback, exec round trip),
    so only call it via ``asyncio.to_thread``.
    """
    _connect_with_fallback(client, connect_kwargs, host_ip)

    # Set up shell channel or execute command
    transport = client.get_transport()
    if not transport:
        return None

    channel = transport.open_session()
    channel.set_combine_stderr(True)  # combine stderr into stdout without allocating a PTY (avoids sudo TCSAFLUSH race)
    channel.exec_command(run_cmd)
    return channel


async def _answer_sudo_prompt(channel, chunk: str, password: str, password_sent: bool) -> tuple[str, bool, bool]:
    """Send the password on the first prompt; a further prompt means sudo rejected it.

    Returns the chunk without prompt markers, whether the password is out, and whether it was rejected.
    """
    if not password_sent:
        await asyncio.sleep(0.05)
        channel.send(f"{password}\n")
        password_sent = True
        chunk = chunk.replace(_SUDO_PROMPT, "", 1)
    rejected = _SUDO_PROMPT in chunk
    if rejected:
        chunk = chunk.replace(_SUDO_PROMPT, "")
    return chunk, password_sent, rejected


async def _emit(output_callback: Callable[[str], Awaitable[None] | None], chunk: str) -> None:
    # An async callback is awaited before the next read: output keeps its order and no
    # fire-and-forget send task outlives the session
    result = output_callback(chunk)
    if inspect.isawaitable(result):
        await result


async def _pump_output(channel, sudo_password: str | None, output_callback) -> bool:
    """Stream the channel to ``output_callback`` until EOF or exit; True when sudo rejected the password.

    Only reads what recv_ready() reports as buffered, so it stays on the event loop. The fixed
    prompt marker is answered whenever it shows up, however late or localised.
    """
    password_sent = False
    while True:
        if channel.recv_ready():
            chunk = channel.recv(4096).decode("utf-8", errors="replace")
            if not chunk:
                return False
            rejected = False
            if sudo_password and _SUDO_PROMPT in chunk:
                chunk, password_sent, rejected = await _answer_sudo_prompt(channel, chunk, sudo_password, password_sent)
            if chunk:
                await _emit(output_callback, chunk)
            if rejected:
                channel.close()
                return True
        elif channel.exit_status_ready() and not channel.recv_ready():
            return False  # finished and nothing left to read
        await asyncio.sleep(0.1)


async def run_ssh_command_stream(
    *,
    host_ip: str,
    ssh_user: str,
    ssh_password: str | None = None,
    ssh_key: str | None = None,
    ssh_port: int = 22,
    command: str,
    output_callback: Callable[[str], Awaitable[None] | None],
    ssh_key_passphrase: str | None = None,
    pinned_host_key: PinnedHostKey | None = None,
    tofu_policy: TofuHostKeyPolicy | None = None,
) -> tuple[bool, str]:
    """Connects to host and executes command, streaming stdout/stderr line-by-line.

    Connect and exec run in a worker thread; the read loop stays on the event loop
    because it only reads what recv_ready() reports as already buffered.
    """
    client = _build_client(pinned_host_key=pinned_host_key, tofu_policy=tofu_policy)

    try:
        connect_kwargs, err = _build_connect_kwargs(host_ip, ssh_user, ssh_port, ssh_password, ssh_key, ssh_key_passphrase)
        if err:
            return False, err

        needs_sudo = ssh_user != "root"
        # As non-root the whole command runs as root in one shell (a plain "sudo <cmd>" left
        # env assignments and $(...) of the update command outside sudo). Without a password
        # it fails fast (passwordless sudo only) instead of waiting for input.
        run_cmd = _with_sudo(f"sh -c {shlex.quote(command)}", ssh_password) if needs_sudo else command

        channel = await asyncio.to_thread(_open_command_channel, client, connect_kwargs, host_ip, run_cmd)
        if channel is None:
            return False, "Failed to get SSH transport channel."

        if await _pump_output(channel, ssh_password if needs_sudo else None, output_callback):
            return False, f"Sudo password rejected on {host_ip} for user '{ssh_user}'. Please check your SSH/sudo password."

        # paramiko has no Channel.get_exit_status(). After an EOF break recv_exit_status()
        # may still wait for the exit-status message, so it runs in a worker thread too.
        exit_code = await asyncio.to_thread(channel.recv_exit_status)
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
    ssh_key_passphrase: str | None = None,
    pinned_host_key: PinnedHostKey | None = None,
    tofu_policy: TofuHostKeyPolicy | None = None,
) -> dict[str, Any]:
    """Queries package updates lists over SSH (Debian/Ubuntu/Fedora/CentOS).

    The whole SSH session (connect, apt-get update of up to 90 s, package queries)
    blocks, so it runs in a worker thread like agent_deployer.deploy_agent.
    """
    return await asyncio.to_thread(
        _list_device_updates_blocking,
        host_ip=host_ip,
        ssh_user=ssh_user,
        ssh_password=ssh_password,
        ssh_key=ssh_key,
        ssh_port=ssh_port,
        ssh_key_passphrase=ssh_key_passphrase,
        pinned_host_key=pinned_host_key,
        tofu_policy=tofu_policy,
    )


def _list_device_updates_blocking(
    *,
    host_ip: str,
    ssh_user: str,
    ssh_password: str | None,
    ssh_key: str | None,
    ssh_port: int,
    ssh_key_passphrase: str | None = None,
    pinned_host_key: PinnedHostKey | None = None,
    tofu_policy: TofuHostKeyPolicy | None = None,
) -> dict[str, Any]:
    """Blocking body of :func:`list_device_updates`; only call it via ``asyncio.to_thread``."""
    client = _build_client(pinned_host_key=pinned_host_key, tofu_policy=tofu_policy)

    try:
        connect_kwargs, err = _build_connect_kwargs(
            host_ip, ssh_user, ssh_port, ssh_password, ssh_key, ssh_key_passphrase
        )
        if err:
            return {"patch_manager": None, "packages": [], "major_upgrade_available": None, "error": err}

        _connect_with_fallback(client, connect_kwargs, host_ip)

        # 1. Detect Package Manager
        _, stdout, _ = client.exec_command("command -v apt-get || command -v dnf || command -v yum", timeout=10)
        pkg_manager_path = stdout.read().decode().strip()
        
        result = {
            "patch_manager": None,
            "packages": [],
            "major_upgrade_available": None
        }

        if not pkg_manager_path:
            # Diagnostic fallback: report what the target system actually is,
            # so the UI shows a useful message instead of a generic one.
            try:
                _, stdout_os, _ = client.exec_command(
                    "cat /etc/os-release 2>/dev/null | grep -E '^(PRETTY_NAME|ID|VERSION_ID)=' || echo 'no /etc/os-release'",
                    timeout=10,
                )
                result["detected_os"] = stdout_os.read().decode().strip()
            except Exception:
                result["detected_os"] = None

        if "apt-get" in pkg_manager_path:
            result["patch_manager"] = "apt"
            _query_apt_updates(client, result, host_ip, ssh_user, ssh_password)

        elif "dnf" in pkg_manager_path:
            result["patch_manager"] = "dnf"
            _query_dnf_updates(client, result)

        elif "yum" in pkg_manager_path:
            result["patch_manager"] = "yum"
            _query_yum_updates(client, result)

        return result

    except Exception as e:
        logger.error("Failed to query package updates over SSH: %s", e)
        return {"patch_manager": None, "packages": [], "major_upgrade_available": None, "error": str(e)}
    finally:
        client.close()


def _with_sudo(command: str, ssh_password: str | None) -> str:
    """``command`` run through sudo: answering the fixed prompt with a password, else never prompting.

    -n (never prompt) only without a password: combined with -S it made sudo refuse
    ("a password is required") before the password could be sent.
    """
    if ssh_password:
        return f"sudo -S -p '{_SUDO_PROMPT}' {command}"
    return f"sudo -n {command}"


def _drain(chan) -> str:
    """Whatever is still buffered on a finished channel."""
    output = ""
    while chan.recv_ready():
        output += chan.recv(4096).decode("utf-8", errors="replace")
    return output


def _read_apt_update(chan, sudo_password: str | None) -> tuple[str, bool]:
    """Read ``apt-get update`` until it ends or 90 s pass; returns (output, sudo rejected the password).

    The channel is read continuously so the PTY buffer never fills up (it used to hang
    forever), and the password goes out only when sudo actually asks (SUDOPROMPT).
    """
    output = ""
    password_sent = False
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if chan.recv_ready():
            chunk = chan.recv(4096).decode("utf-8", errors="replace")
            output += chunk
            if sudo_password and _SUDO_PROMPT in chunk:
                if not password_sent:
                    time.sleep(0.05)
                    chan.send(f"{sudo_password}\n")
                    password_sent = True
                    chunk = chunk.replace(_SUDO_PROMPT, "", 1)
                if _SUDO_PROMPT in chunk or output.count(_SUDO_PROMPT) >= 2:
                    chan.close()
                    return output, True
            elif password_sent and output.count(_SUDO_PROMPT) >= 2:
                chan.close()
                return output, True
        elif chan.exit_status_ready():
            return output + _drain(chan), False
        time.sleep(0.1)
    return output, False


def _record_apt_update_failure(
    result: dict[str, Any], host_ip: str, ssh_user: str, needs_sudo: bool, ssh_password: str | None,
    output: str, sudo_rejected: bool, exit_code: int | None,
) -> None:
    """Note a rejected sudo password or a failed refresh in ``result`` (the package list is still read)."""
    if sudo_rejected:
        logger.warning("apt-get update on %s aborted: sudo rejected password for user '%s'", host_ip, ssh_user)
        result["sudo_rejected"] = True
        result["error"] = (
            f"Sudo password rejected on {host_ip} for user '{ssh_user}'. "
            "Please check your SSH/sudo password or enable passwordless sudo."
        )
    elif exit_code != 0:
        logger.warning("apt-get update on %s failed (exit %s): %s", host_ip, exit_code, output.strip()[-500:])
        # Only without a password can sudo be the reason; otherwise it is the repositories or the network
        hint = " Set an SSH password or enable passwordless sudo to refresh package lists." if needs_sudo and not ssh_password else ""
        result["error"] = "apt-get update failed (exit %s).%s" % (exit_code if exit_code is not None else "timeout", hint)


# package/suite version arch [upgradable from: old_version], e.g.
# curl/jammy-updates 7.81.0-1ubuntu1.16 amd64 [upgradable from: 7.81.0-1ubuntu1.15]
_APT_UPGRADABLE = re.compile(r"^([^/]+)/([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+\[upgradable from:\s+([^\]]+)\]")


def _parse_apt_upgradable(output: str) -> list[dict[str, str]]:
    """Packages from ``apt list --upgradable``."""
    packages = []
    for line in output.splitlines():
        match = _APT_UPGRADABLE.match(line) if "upgradable from" in line else None
        if match:
            pkg_name, suite, new_ver, _arch, old_ver = match.groups()
            packages.append({"package": pkg_name, "current_version": old_ver, "new_version": new_ver, "repo": suite})
    return packages


def _parse_release_upgrade(output: str) -> str | None:
    """The release named in ``do-release-upgrade -c`` ("New release '24.04 LTS' available"), the last one wins."""
    release = None
    for line in output.splitlines():
        parts = line.split("'")
        if "New release" in line and "available" in line and len(parts) >= 3:
            release = parts[1]
    return release


def _query_apt_updates(client, result: dict[str, Any], host_ip: str, ssh_user: str, ssh_password: str | None) -> None:
    """Populate apt upgrade results (refresh cache + parse 'apt list --upgradable').

    Blocking; runs inside :func:`_list_device_updates_blocking`'s worker thread.
    """
    # Refresh the package cache first (needs root)
    needs_sudo = ssh_user != "root"
    chan = client.get_transport().open_session()
    chan.set_combine_stderr(True)
    chan.exec_command(_with_sudo("apt-get update", ssh_password) if needs_sudo else "apt-get update")

    output, sudo_rejected = _read_apt_update(chan, ssh_password if needs_sudo else None)
    exit_code = None if sudo_rejected else (chan.recv_exit_status() if chan.exit_status_ready() else None)
    _record_apt_update_failure(result, host_ip, ssh_user, needs_sudo, ssh_password, output, sudo_rejected, exit_code)

    _, stdout, _ = client.exec_command("apt list --upgradable 2>/dev/null", timeout=15)
    result["packages"].extend(_parse_apt_upgradable(stdout.read().decode("utf-8")))

    # Major release upgrade (Ubuntu only)
    _, stdout, _ = client.exec_command("which do-release-upgrade", timeout=5)
    if stdout.read().decode().strip():
        _, stdout, _ = client.exec_command("do-release-upgrade -c", timeout=10)
        release = _parse_release_upgrade(stdout.read().decode("utf-8"))
        if release is not None:
            result["major_upgrade_available"] = release


def _parse_check_update(output: str, skip_metadata_line: bool) -> list[dict[str, str]]:
    """Packages from ``dnf/yum check-update``: ``curl.x86_64   7.81.0-1.fc39   updates``."""
    upgrades = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 3 or (skip_metadata_line and line.startswith("Last metadata")):
            continue
        upgrades.append({
            "package": parts[0].rsplit(".", 1)[0],
            "new_version": parts[1],
            "repo": parts[2],
            "current_version": "Installed",  # until rpm says otherwise
        })
    return upgrades


def _installed_versions(client, pkg_names: list[str]) -> dict[str, str]:
    """Installed versions of up to 100 packages in one ``rpm -q`` call."""
    quoted_pkgs = " ".join(shlex.quote(p) for p in pkg_names[:100])
    batch_cmd = f"rpm -q --qf '%{{NAME}} %{{VERSION}}-%{{RELEASE}}\\n' {quoted_pkgs}"
    _, stdout_rpm, _ = client.exec_command(batch_cmd, timeout=10)
    versions = {}
    for line in stdout_rpm.read().decode("utf-8").splitlines():
        subparts = line.split()
        if len(subparts) == 2:
            versions[subparts[0]] = subparts[1]
    return versions


def _query_dnf_updates(client, result: dict[str, Any]) -> None:
    """Populate dnf upgrade results (check-update + batch rpm current versions); blocking."""
    _, stdout, _ = client.exec_command("dnf check-update --quiet", timeout=20)
    upgrades = _parse_check_update(stdout.read().decode("utf-8"), skip_metadata_line=True)
    if upgrades:
        versions = _installed_versions(client, [item["package"] for item in upgrades])
        for item in upgrades:
            item["current_version"] = versions.get(item["package"], item["current_version"])
    result["packages"] = upgrades


def _query_yum_updates(client, result: dict[str, Any]) -> None:
    """Populate yum upgrade results (check-update); blocking."""
    _, stdout, _ = client.exec_command("yum check-update --quiet", timeout=20)
    result["packages"] = _parse_check_update(stdout.read().decode("utf-8"), skip_metadata_line=False)
