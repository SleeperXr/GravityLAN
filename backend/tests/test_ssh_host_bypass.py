"""The Docker bridge gateway fallback only applies to the Docker host itself (#46)."""
import socket
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services import patch_service, ssh_terminal
from app.services.docker_service import docker_service
from app.services.ssh_utils import connect_with_gateway_fallback, host_bypass_gateway

GATEWAY = "172.17.0.1"
DEVICE = "192.168.1.80"
DOCKER_HOST = "192.168.1.10"


@pytest.fixture(autouse=True)
def bridge_gateway(monkeypatch):
    monkeypatch.setattr(docker_service, "get_bridge_gateway", lambda: GATEWAY)
    monkeypatch.delenv("DOCKER_HOST_IP", raising=False)
    monkeypatch.setattr(settings, "docker_host_ip", "")


def _offline_client():
    client = MagicMock()
    client.connect.side_effect = TimeoutError("device is switched off")
    return client


@pytest.mark.parametrize("docker_host", ["", DOCKER_HOST])
def test_offline_device_never_falls_back_to_docker_host(monkeypatch, docker_host):
    monkeypatch.setattr(settings, "docker_host_ip", docker_host)
    for connect in (connect_with_gateway_fallback, patch_service._connect_with_fallback):
        client = _offline_client()
        with pytest.raises(TimeoutError):
            connect(client, {"hostname": DEVICE, "port": 22, "username": "root", "password": "pw"}, DEVICE)
        assert [c.kwargs["hostname"] for c in client.connect.call_args_list] == [DEVICE]


@pytest.mark.parametrize("configure", ["setting", "legacy_env"])
def test_docker_host_itself_retries_on_gateway(monkeypatch, configure):
    if configure == "setting":
        monkeypatch.setattr(settings, "docker_host_ip", DOCKER_HOST)
    else:
        monkeypatch.setenv("DOCKER_HOST_IP", DOCKER_HOST)
    assert host_bypass_gateway(DOCKER_HOST) == GATEWAY

    client = MagicMock()
    client.connect.side_effect = [TimeoutError("macvlan: host not reachable"), None]
    connect_with_gateway_fallback(client, {"hostname": DOCKER_HOST, "port": 22, "username": "root"}, DOCKER_HOST)
    assert [c.kwargs["hostname"] for c in client.connect.call_args_list] == [DOCKER_HOST, GATEWAY]


def test_terminal_does_not_open_docker_host_for_offline_device(monkeypatch):
    targets = []

    def refuse(address, timeout=None):
        targets.append(address[0])
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr(socket, "create_connection", refuse)
    with pytest.raises(ssh_terminal.TerminalError):
        ssh_terminal._open_socket(DEVICE, 22)
    assert targets == [DEVICE]
