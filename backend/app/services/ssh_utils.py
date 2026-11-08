"""Shared SSH utilities for remote command execution.

Extracted from agent_deployer.py to:
- Reduce co-change scatter (ungoverned_hotspot, co_change_scatter)
- Enable unit testing without paramiko mocks in consumer modules
- Provide stable interface for future SSH-based operations
"""

from __future__ import annotations

import io
import logging
import os
import shlex
import time
from dataclasses import dataclass
from typing import Optional

import paramiko

from app.config import settings
from app.services.ppk import PpkPassphraseRequired, is_ppk, ppk_to_openssh

logger = logging.getLogger(__name__)


class CustomWarningPolicy(paramiko.WarningPolicy):
    """Custom warning policy for missing host keys to satisfy CodeQL static analysis."""
    pass


class SSHKeyPassphraseRequired(ValueError):
    """Raised when a private key is encrypted and no (or a wrong) passphrase was given."""
    pass


# DSA keys are gone since paramiko 4; OpenSSH dropped them long before.
_KEY_CLASSES = (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey)


def load_private_key(ssh_key: str, passphrase: Optional[str] = None) -> paramiko.PKey:
    """Load an SSH private key (Ed25519, ECDSA or RSA) from its text form.

    Accepts OpenSSH/PEM and PuTTY (.ppk, format 2 and 3) keys.

    Raises:
        SSHKeyPassphraseRequired: The key is encrypted and the passphrase is missing or wrong.
        ValueError: The text is not a supported private key.
    """
    if is_ppk(ssh_key):
        ssh_key, passphrase = ppk_as_openssh(ssh_key, passphrase), None

    key, needs_passphrase, errors = _try_key_classes(ssh_key, passphrase or None)
    if key is not None:
        return key
    # A wrong passphrase only shows up as a decode error, so probe whether the key is encrypted at all.
    if needs_passphrase or (passphrase and _try_key_classes(ssh_key, None)[1]):
        raise SSHKeyPassphraseRequired("The private key is encrypted: passphrase missing or wrong.")
    raise ValueError(f"Invalid or unsupported private key format. Details: {'; '.join(errors)}")


def ppk_as_openssh(ssh_key: str, passphrase: Optional[str] = None) -> str:
    """Convert a PuTTY key to OpenSSH text, mapping its passphrase error to SSHKeyPassphraseRequired."""
    try:
        return ppk_to_openssh(ssh_key, passphrase)
    except PpkPassphraseRequired as exc:
        raise SSHKeyPassphraseRequired(str(exc)) from exc


def _try_key_classes(ssh_key: str, passphrase: Optional[str]) -> tuple[Optional[paramiko.PKey], bool, list[str]]:
    """Try every supported key class; returns (key, passphrase_required, errors)."""
    errors = []
    needs_passphrase = False
    for key_cls in _KEY_CLASSES:
        try:
            return key_cls.from_private_key(io.StringIO(ssh_key.strip() + "\n"), password=passphrase), False, []
        except paramiko.PasswordRequiredException:
            needs_passphrase = True
        except Exception as e:
            errors.append(f"{key_cls.__name__}: {e}")
    return None, needs_passphrase, errors


# Backwards-compatible name used by patch_service.
_load_ssh_key = load_private_key


def build_ssh_client() -> paramiko.SSHClient:
    """Create an SSH client with host key policy based on settings."""
    client = paramiko.SSHClient()
    if settings.ssh_strict_mode:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(CustomWarningPolicy())
    return client


@dataclass(frozen=True)
class PinnedHostKey:
    """A host key the user confirmed in the SSH terminal (an ``ssh_known_hosts`` entry)."""

    key_type: str
    fingerprint: str


class HostKeyNotTrusted(paramiko.SSHException):
    """The server presented a key other than the pinned one; raised before any credential is sent."""
    pass


class PinnedHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Accept exactly the pinned key, whatever address answered (also on the bridge-gateway fallback)."""

    def __init__(self, pinned: PinnedHostKey):
        self._pinned = pinned

    def missing_host_key(self, client, hostname, key) -> None:
        if key.get_name() == self._pinned.key_type and key.fingerprint == self._pinned.fingerprint:
            return
        raise HostKeyNotTrusted(f"Host key {key.get_name()} {key.fingerprint} of {hostname} is not the confirmed one")


def build_pinned_ssh_client(pinned: PinnedHostKey) -> paramiko.SSHClient:
    """SSH client that only talks to a server presenting ``pinned``.

    No other host keys are loaded, so paramiko hands every server key to the
    policy, which runs after the key exchange and before authentication.
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedHostKeyPolicy(pinned))
    return client


@dataclass(frozen=True)
class CapturedHostKey:
    """A host key captured during trust-on-first-use handshake."""

    key_type: str
    fingerprint: str
    public_key: str


class TofuHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Accepts an unknown host key on first contact and records it for DB persistence."""

    def __init__(self) -> None:
        self.captured: Optional[CapturedHostKey] = None

    def missing_host_key(self, client, hostname, key) -> None:
        self.captured = CapturedHostKey(
            key_type=key.get_name(),
            fingerprint=key.fingerprint,
            public_key=f"{key.get_name()} {key.get_base64()}",
        )


def build_connect_kwargs(
    host_ip: str,
    ssh_user: str,
    ssh_port: int,
    ssh_password: Optional[str],
    ssh_key: Optional[str],
    ssh_key_passphrase: Optional[str] = None,
) -> tuple[dict, Optional[str]]:
    """Build connection kwargs for paramiko client.connect.

    Args:
        host_ip: Target hostname or IP
        ssh_user: SSH username
        ssh_port: SSH port (default 22)
        ssh_password: Optional password (only used for sudo when a key is given)
        ssh_key: Optional private key string (OpenSSH format)
        ssh_key_passphrase: Passphrase of an encrypted ``ssh_key``

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
            connect_kwargs["pkey"] = _load_ssh_key(ssh_key, ssh_key_passphrase)
        except ValueError as e:
            logger.error("SSH private key loading failed: %s", e)
            return {}, "Invalid SSH key format or encrypted key."
    elif ssh_password:
        connect_kwargs["password"] = ssh_password
    else:
        return {}, "Neither password nor SSH key provided."

    return connect_kwargs, None


def host_bypass_gateway(host_ip: str) -> Optional[str]:
    """The Docker bridge gateway to retry an SSH login on, or None.

    A container sometimes cannot reach its own host by the host's LAN address (macvlan),
    but can through the bridge gateway. That is the same machine only when ``host_ip`` is
    the configured Docker host; for any other device the retry would run the action on
    the Docker host instead (#46), so a failed connection stays failed.
    """
    docker_host = (settings.docker_host_ip or os.getenv("DOCKER_HOST_IP") or "").strip()
    if not docker_host or host_ip != docker_host:
        return None
    from app.services.docker_service import docker_service
    gateway = docker_service.get_bridge_gateway()
    return gateway if gateway and gateway != host_ip else None


def connect_with_gateway_fallback(
    client: paramiko.SSHClient,
    connect_kwargs: dict,
    host_ip: str,
) -> None:
    """Attempt SSH connection, retrying on the bridge gateway only for the Docker host itself (blocking)."""
    try:
        client.connect(**connect_kwargs)
        return
    except (paramiko.SSHException, OSError):
        gateway = host_bypass_gateway(host_ip)
        if not gateway:
            raise

    logger.info("Direct connection failed. Attempting Host Bypass via bridge gateway: %s", gateway)
    connect_kwargs["hostname"] = gateway
    client.connect(**connect_kwargs)


class RemoteRunner:
    """Executes commands on a remote host via paramiko, handling sudo and timeouts."""

    def __init__(self, client: paramiko.SSHClient, has_sudo: bool, ssh_user: str, ssh_password: Optional[str]):
        self._client = client
        self._has_sudo = has_sudo
        self._ssh_user = ssh_user
        self._ssh_password = ssh_password

    @property
    def _needs_sudo_wrap(self) -> bool:
        return self._has_sudo and self._ssh_user != "root"

    @property
    def _sudo_password(self) -> Optional[str]:
        return self._ssh_password if self._needs_sudo_wrap else None

    def _wrap_sudo(self, command: str) -> str:
        if not self._needs_sudo_wrap:
            return command
        # Use -S with empty prompt when a password is available, or -n (non-interactive) without one.
        # Run via sh -c with shlex.quote to avoid any heredoc stdin conflict with sudo's password reading.
        if self._sudo_password:
            return f"sudo -S -p '' -- sh -c {shlex.quote(command)}"
        return f"sudo -n -- sh -c {shlex.quote(command)}"

    def run(self, command: str, timeout: int = 15) -> str:
        """Execute a single command, raising on non-zero exit (except benign 1 for 'not found')."""
        wrapped = self._wrap_sudo(command)
        return _exec_impl(self._client, wrapped, timeout, self._sudo_password)

    def run_batch(self, commands: list[str], timeout: int = 15) -> list[str]:
        """Execute multiple commands sequentially."""
        return [self.run(cmd, timeout) for cmd in commands]

    def run_sudo_batch(self, commands: list[str], timeout: int = 15) -> str:
        """Execute multiple commands in a single sudo execution."""
        full_cmd = "set -e\n" + " && ".join(commands)
        wrapped = self._wrap_sudo(full_cmd)
        return _exec_impl(self._client, wrapped, timeout, self._sudo_password)


class RemoteCommandError(RuntimeError):
    """A remote command failed; the message is meant for the user and never holds the command itself
    (staged files carry the agent token)."""


class SudoPasswordError(RemoteCommandError):
    """sudo needed a password it did not get, or refused the one it got."""


class RemoteTimeoutError(RemoteCommandError):
    """A remote command did not finish in time."""


# sudo's "password needed" in English and the German translations seen in the field
_SUDO_PASSWORD_NEEDED = ("a password is required", "passwort erforderlich", "es wurde kein passwort angegeben", "ein passwort ist notwendig")
_SUDO_PASSWORD_WRONG = ("incorrect password", "falsches passwort", "nicht funktioniert", "fehlversuch")


def _feed_sudo_password(stdin, command: str, sudo_pass: Optional[str]) -> None:
    """Answer the password prompt of ``sudo -S`` on stdin, then close stdin."""
    if sudo_pass and "sudo -S" in command:
        stdin.write(f"{sudo_pass}\n")
        stdin.flush()
        try:
            stdin.channel.shutdown_write()
        except (paramiko.SSHException, OSError, EOFError) as exc:
            logger.debug("Closing stdin channel failed: %s", exc)


def _wait_for_exit(stdout, command: str, timeout: int) -> None:
    """Wait until the command ends; close the channel and raise RemoteTimeoutError after ``timeout`` seconds."""
    start_time = time.time()
    while not stdout.channel.exit_status_ready():
        if time.time() - start_time > timeout:
            stdout.channel.close()
            logger.warning("Remote command timed out after %ds", timeout)
            hint = " sudo may be waiting for a password." if "sudo -n" in command else ""
            raise RemoteTimeoutError(f"A command on the host did not finish within {timeout}s.{hint}")
        time.sleep(0.1)


def _is_benign_not_found(exit_code: int, err: str) -> bool:
    """Return True if exit code 1 represents a benign 'not found' / 'no such' command result."""
    if exit_code != 1:
        return False
    err_lower = err.lower()
    return "not found" in err_lower or "no such" in err_lower


def _extract_error_detail(output_text: str) -> str:
    """Extract a sanitized single-line summary of the last error output line."""
    if not output_text:
        return ""
    last_line = output_text.splitlines()[-1][:200]
    return f": {last_line}" if last_line else ""


def _check_exit(exit_code: int, out: str, err: str) -> str:
    """The output of a finished command, or the readable error its exit code and stderr stand for."""
    if exit_code == 0 or _is_benign_not_found(exit_code, err):
        return out

    err_lower = (err or out).lower()
    if any(term in err_lower for term in _SUDO_PASSWORD_NEEDED):
        raise SudoPasswordError(
            "sudo needs a password for this user. Enter the user's password; it is used for sudo and not stored."
        )
    if any(term in err_lower for term in _SUDO_PASSWORD_WRONG):
        raise SudoPasswordError(
            "Sudo password rejected by remote host. Please check your SSH / sudo password."
        )

    # Not the command itself: staged files (heredocs) carry the agent token
    logger.warning("Remote command failed (exit %d): %s", exit_code, err)
    detail = _extract_error_detail(err or out)
    raise RemoteCommandError(f"A command on the host failed (exit {exit_code}){detail}.")


def _exec_impl(client: paramiko.SSHClient, command: str, timeout: int, sudo_pass: Optional[str]) -> str:
    """Low-level command execution with sudo password support and timeout handling."""
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    _feed_sudo_password(stdin, command, sudo_pass)
    _wait_for_exit(stdout, command, timeout)

    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode(errors='ignore').strip()
    err = stderr.read().decode(errors='ignore').strip()
    return _check_exit(exit_code, out, err)
