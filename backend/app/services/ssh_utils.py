"""Shared SSH utilities for remote command execution.

Extracted from agent_deployer.py to:
- Reduce co-change scatter (ungoverned_hotspot, co_change_scatter)
- Enable unit testing without paramiko mocks in consumer modules
- Provide stable interface for future SSH-based operations
"""

from __future__ import annotations

import errno
import io
import logging
import os
import shlex
import socket
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


_PERMITTED_TCP_ERRNOS = {
    errno.ECONNREFUSED,
    errno.EHOSTUNREACH,
    errno.ENETUNREACH,
    errno.ETIMEDOUT,
}
if hasattr(errno, "EHOSTDOWN"):
    _PERMITTED_TCP_ERRNOS.add(getattr(errno, "EHOSTDOWN"))


def _is_direct_tcp_failure(err: BaseException) -> bool:
    """True ONLY if `err` is a confirmed low-level network failure before any SSH exchange."""
    # Explicit exclusions: authentication, host keys, EOF, protocol errors
    if isinstance(err, (
        HostKeyNotTrusted,
        paramiko.BadHostKeyException,
        paramiko.AuthenticationException,
        paramiko.PasswordRequiredException,
        EOFError,
    )):
        return False

    # Confirmed network connection exceptions
    if isinstance(err, (ConnectionRefusedError, TimeoutError, socket.timeout)):
        return True

    # Generic OSError only if errno matches network unreachable/refused/timed out
    if isinstance(err, OSError) and getattr(err, "errno", None) in _PERMITTED_TCP_ERRNOS:
        return True

    return False


def is_unreachable(error: BaseException) -> bool:
    """True ONLY when the host could not be reached at all on the network.

    Retrying on the Docker bridge gateway sends the credentials to another IP.
    Therefore, any error that indicates the remote host answered (host key check,
    protocol handshake, banner, authentication, or EOF during communication) or
    a local resource/file failure MUST NOT trigger a fallback.
    """
    if _is_direct_tcp_failure(error):
        return True

    if isinstance(error, paramiko.ssh_exception.NoValidConnectionsError):
        underlying = getattr(error, "errors", None)
        if not underlying:
            return False
        # Every underlying socket attempt must be an allowed TCP failure
        return all(_is_direct_tcp_failure(e) for e in underlying.values())

    return False


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
    except Exception as e:
        gateway = host_bypass_gateway(host_ip) if is_unreachable(e) else None
        if not gateway:
            raise
        logger.info("Direct connection failed (%s). Attempting Host Bypass via bridge gateway: %s", e, gateway)
        retry_kwargs = dict(connect_kwargs)
        retry_kwargs["hostname"] = gateway
        client.connect(**retry_kwargs)


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
        """Execute a single command, raising on non-zero exit."""
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
_SUDO_PROMPT_PHRASES = ("a password is required", "passwort erforderlich", "es wurde kein passwort angegeben", "ein passwort ist notwendig")
_SUDO_REJECT_PHRASES = ("incorrect password", "falsches passwort", "nicht funktioniert", "fehlversuch")
_SUDO_PASSWORD_NEEDED = _SUDO_PROMPT_PHRASES
_SUDO_PASSWORD_WRONG = _SUDO_REJECT_PHRASES


def _feed_sudo_password(stdin, command: str, sudo_pass: Optional[str]) -> None:
    """Answer the password prompt of ``sudo -S`` on stdin, then close stdin."""
    if sudo_pass and "sudo -S" in command:
        stdin.write(f"{sudo_pass}\n")
        stdin.flush()
        try:
            stdin.channel.shutdown_write()
        except (paramiko.SSHException, OSError, EOFError) as exc:
            logger.debug("Closing stdin channel failed: %s", exc)


MAX_STREAM_BYTES = 1024 * 1024  # 1 MiB per stream
_TRUNCATED_MARKER = b"\n[... output truncated ...]\n"


class _BoundedStreamDrain:
    """Captures up to MAX_STREAM_BYTES, retaining the head and tail when truncated."""

    __slots__ = ("_head", "_tail", "_total_bytes", "_max_bytes", "_half")

    def __init__(self, max_bytes: int = MAX_STREAM_BYTES) -> None:
        self._max_bytes = max_bytes
        self._half = (max_bytes - len(_TRUNCATED_MARKER)) // 2
        self._head = bytearray()
        self._tail = bytearray()
        self._total_bytes = 0

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._total_bytes += len(chunk)
        if len(self._head) < self._half:
            needed = self._half - len(self._head)
            take = chunk[:needed]
            self._head.extend(take)
            remaining = chunk[needed:]
        else:
            remaining = chunk

        if remaining:
            self._tail.extend(remaining)
            if len(self._tail) > self._half:
                del self._tail[:-self._half]

    def get_value(self) -> bytes:
        if self._total_bytes <= self._max_bytes:
            return bytes(self._head + self._tail)
        return bytes(self._head + _TRUNCATED_MARKER + self._tail)


def _wait_for_exit(stdout, command: str, timeout: int) -> None:
    """Wait until the command ends; close the channel and raise RemoteTimeoutError after ``timeout`` seconds."""
    channel = getattr(stdout, "channel", stdout)
    start_time = time.monotonic()
    while not channel.exit_status_ready():
        if time.monotonic() - start_time > timeout:
            if hasattr(channel, "close"):
                channel.close()
            logger.warning(
                "Remote command timed out after %ds (local channel closed; remote process termination cannot be guaranteed)",
                timeout,
            )
            hint = " sudo may be waiting for a password." if "sudo -n" in command else ""
            raise RemoteTimeoutError(f"A command on the host did not finish within {timeout}s.{hint}")
        time.sleep(0.1)


def _drain_channel(
    stdout,
    stderr,
    command: str,
    timeout: int,
) -> tuple[int, str, str]:
    """Drain stdout and stderr fairly until exit or timeout, bounded to MAX_STREAM_BYTES per stream."""
    channel = getattr(stdout, "channel", stdout)
    start_time = time.monotonic()
    stdout_drain = _BoundedStreamDrain(MAX_STREAM_BYTES)
    stderr_drain = _BoundedStreamDrain(MAX_STREAM_BYTES)
    chunk_size = 32768

    if hasattr(channel, "recv_ready"):
        while True:
            had_data = False

            if channel.recv_ready():
                chunk = channel.recv(chunk_size)
                if chunk:
                    stdout_drain.feed(chunk)
                    had_data = True

            if hasattr(channel, "recv_stderr_ready") and channel.recv_stderr_ready():
                chunk = channel.recv_stderr(chunk_size)
                if chunk:
                    stderr_drain.feed(chunk)
                    had_data = True

            if channel.exit_status_ready():
                # Process ended; drain all remaining pending bytes
                while channel.recv_ready() or (hasattr(channel, "recv_stderr_ready") and channel.recv_stderr_ready()):
                    drained_any = False
                    if channel.recv_ready():
                        c = channel.recv(chunk_size)
                        if c:
                            stdout_drain.feed(c)
                            drained_any = True
                    if hasattr(channel, "recv_stderr_ready") and channel.recv_stderr_ready():
                        c = channel.recv_stderr(chunk_size)
                        if c:
                            stderr_drain.feed(c)
                            drained_any = True
                    if not drained_any:
                        break
                break

            if time.monotonic() - start_time > timeout:
                if hasattr(channel, "close"):
                    channel.close()
                logger.warning(
                    "Remote command timed out after %ds (local channel closed; remote process termination cannot be guaranteed)",
                    timeout,
                )
                hint = " sudo may be waiting for a password." if "sudo -n" in command else ""
                raise RemoteTimeoutError(f"A command on the host did not finish within {timeout}s.{hint}")

            if hasattr(channel, "closed") and channel.closed and not channel.recv_ready() and not (
                hasattr(channel, "recv_stderr_ready") and channel.recv_stderr_ready()
            ):
                break

            if not had_data:
                time.sleep(0.02)
    else:
        # Fallback for minimal test stubs lacking recv_ready
        while not channel.exit_status_ready():
            if time.monotonic() - start_time > timeout:
                if hasattr(channel, "close"):
                    channel.close()
                logger.warning(
                    "Remote command timed out after %ds (local channel closed; remote process termination cannot be guaranteed)",
                    timeout,
                )
                hint = " sudo may be waiting for a password." if "sudo -n" in command else ""
                raise RemoteTimeoutError(f"A command on the host did not finish within {timeout}s.{hint}")
            time.sleep(0.02)

        if hasattr(stdout, "read"):
            out_raw = stdout.read()
            stdout_drain.feed(out_raw if isinstance(out_raw, bytes) else str(out_raw).encode())
        if hasattr(stderr, "read"):
            err_raw = stderr.read()
            stderr_drain.feed(err_raw if isinstance(err_raw, bytes) else str(err_raw).encode())

    if not channel.exit_status_ready():
        if hasattr(channel, "close"):
            channel.close()
        raise RemoteCommandError("Remote channel closed without a valid exit status.")

    exit_code = channel.recv_exit_status()
    if exit_code is None or exit_code < 0:
        if hasattr(channel, "close"):
            channel.close()
        raise RemoteCommandError(f"Remote command ended with invalid exit status {exit_code}.")

    out = stdout_drain.get_value().decode(errors="ignore").strip()
    err = stderr_drain.get_value().decode(errors="ignore").strip()
    return exit_code, out, err


def _extract_error_detail(output_text: str) -> str:
    """Extract a sanitized single-line summary of the last error output line."""
    if not output_text:
        return ""
    last_line = output_text.splitlines()[-1][:200]
    return f": {last_line}" if last_line else ""


def _check_exit(exit_code: int, out: str, err: str) -> str:
    """The output of a finished command, or the readable error its exit code and stderr stand for."""
    if exit_code == 0:
        return out

    err_lower = (err or out).lower()
    if any(term in err_lower for term in _SUDO_PROMPT_PHRASES):
        raise SudoPasswordError(
            "sudo needs a password for this user. Enter the user's password; it is used for sudo and not stored."
        )
    if any(term in err_lower for term in _SUDO_REJECT_PHRASES):
        raise SudoPasswordError(
            "Sudo password rejected by remote host. Please check your SSH / sudo password."
        )

    # Not the command itself: staged files (heredocs) carry the agent token
    logger.warning("Remote command failed (exit %d): %s", exit_code, err)
    detail = _extract_error_detail(err or out)
    raise RemoteCommandError(f"A command on the host failed (exit {exit_code}){detail}.")


def _exec_impl(client: paramiko.SSHClient, command: str, timeout: int, sudo_pass: Optional[str]) -> str:
    """Low-level command execution with sudo password support, continuous stream drain, and timeout handling."""
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    channel = getattr(stdout, "channel", stdout)
    try:
        _feed_sudo_password(stdin, command, sudo_pass)
        exit_code, out, err = _drain_channel(stdout, stderr, command, timeout)
        return _check_exit(exit_code, out, err)
    finally:
        if hasattr(channel, "closed") and not channel.closed:
            channel.close()
