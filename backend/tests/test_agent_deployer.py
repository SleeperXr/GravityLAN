"""Regression tests for app/services/agent_deployer.py.

Covers two defects:
- deploy/remove ran blocking paramiko calls on the event loop, freezing the
  whole server (API, WebSockets, scheduler) for the duration of an SSH session.
- the remote cleanup stopped a generic ``agent.service`` and ``pkill -f``-ed any
  ``*agent.py`` process, and its pattern also matched the invoking shell itself.
"""

import asyncio
import re
import time
from unittest.mock import MagicMock

import pytest

from app.services import agent_deployer


# --- event loop must stay responsive during SSH work ------------------------

def _slow_failing_client(delay: float = 0.5) -> MagicMock:
    """SSH client whose connect() blocks like a real TCP/SSH handshake, then fails."""
    client = MagicMock()

    def slow_connect(**_kwargs):
        time.sleep(delay)
        raise OSError("connection refused")

    client.connect.side_effect = slow_connect
    return client


async def _run_counting_loop_ticks(coro):
    """Await ``coro`` while counting how often the event loop could run another task."""
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        result = await coro
    finally:
        task.cancel()
    return result, ticks


@pytest.fixture
def no_docker_gateway(monkeypatch):
    from app.services.docker_service import docker_service
    monkeypatch.setattr(docker_service, "get_bridge_gateway", lambda: None)


@pytest.mark.asyncio
async def test_deploy_agent_does_not_block_event_loop(monkeypatch, no_docker_gateway):
    monkeypatch.setattr(agent_deployer, "build_ssh_client", lambda: _slow_failing_client())

    (success, _message, token), ticks = await _run_counting_loop_ticks(
        agent_deployer.deploy_agent(
            host_ip="192.0.2.10",
            ssh_user="admin",
            ssh_password="pw",
            server_url="http://gravity.local:8000",
            device_id=1,
        )
    )

    assert success is False
    assert token == ""
    # 0.5 s of blocking connect: a free loop ticks ~20-50 times, a blocked one ~0.
    assert ticks >= 10


@pytest.mark.asyncio
async def test_remove_agent_does_not_block_event_loop(monkeypatch, no_docker_gateway):
    monkeypatch.setattr(agent_deployer, "build_ssh_client", lambda: _slow_failing_client())

    (success, _message), ticks = await _run_counting_loop_ticks(
        agent_deployer.remove_agent(host_ip="192.0.2.10", ssh_user="admin", ssh_password="pw")
    )

    assert success is False
    assert ticks >= 10


# --- remote cleanup must only touch GravityLAN's own agent ------------------

_OWN_AGENT_PROCESSES = [
    "/usr/bin/python3 /opt/gravitylan-agent/gravitylan-agent.py",
    "/usr/bin/python3 /opt/gravitylan/gravitylan-agent.py",
    "/usr/bin/python3 /opt/homelan/homelan-agent.py",
]

_FOREIGN_PROCESSES = [
    "python3 /home/pi/agent.py",
    "/usr/bin/python3 /srv/backup/backup_agent.py",
    "/usr/bin/python3 /opt/monitoring/my-agent.py",
]


def _cleanup_commands() -> list[str]:
    return agent_deployer._build_cleanup_script(has_systemd=True, has_syno_rc=False)


def _pkill_patterns(commands: list[str]) -> list[str]:
    patterns = []
    for cmd in commands:
        match = re.search(r"\bpkill\b[^']*'([^']+)'", cmd)
        if match:
            patterns.append(match.group(1))
    return patterns


def test_cleanup_only_stops_gravitylan_units():
    for cmd in _cleanup_commands():
        if cmd.startswith(("systemctl stop", "systemctl disable")):
            units = [word for word in cmd.split() if word.endswith(".service")]
            assert units, cmd
            foreign = [u for u in units if not u.startswith(("gravitylan-", "homelan-"))]
            assert not foreign, f"cleanup would stop foreign units {foreign}: {cmd}"


def test_cleanup_pkill_targets_only_gravitylan_agents():
    patterns = _pkill_patterns(_cleanup_commands())
    assert patterns

    for proc in _OWN_AGENT_PROCESSES:
        assert any(re.search(p, proc) for p in patterns), f"own agent not stopped: {proc}"
    for proc in _FOREIGN_PROCESSES:
        assert not any(re.search(p, proc) for p in patterns), f"foreign process killed: {proc}"


def test_cleanup_pkill_does_not_match_invoking_shell():
    """pkill -f skips itself but not its parent shell, whose argv holds the pattern."""
    commands = _cleanup_commands()
    # RemoteRunner.run: one `sh -c <cmd>` per command (root user, no sudo wrap).
    # RemoteRunner.run_sudo_batch: all commands joined into one heredoc.
    shell_argvs = [f"sh -c {cmd}" for cmd in commands] + [f"sh -c {' && '.join(commands)}"]

    for pattern in _pkill_patterns(commands):
        for argv in shell_argvs:
            assert not re.search(pattern, argv), f"'{pattern}' would kill its own shell: {argv}"


def test_pkill_pattern_for_agent_path_skips_own_shell():
    pattern = agent_deployer._pkill_pattern_for(agent_deployer.REMOTE_AGENT_PATH)
    own_shell = f"sh -c pkill -f '{pattern}' || true"

    assert re.search(pattern, f"/usr/bin/python3 {agent_deployer.REMOTE_AGENT_PATH}")
    assert not re.search(pattern, own_shell)
