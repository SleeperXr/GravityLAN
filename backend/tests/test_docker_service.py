"""Tests for the Docker service discovery (app/services/docker_service.py)."""

from unittest.mock import MagicMock

import app.services.docker_service as docker_service_module


class FakeContainer:
    def __init__(self, short_id, name, status, ips, image_tags=("latest",), state=None):
        self.short_id = short_id
        self.name = name
        self.status = status
        self.image = MagicMock(tags=image_tags)
        self.attrs = {
            "NetworkSettings": {"Networks": {n: {"IPAddress": ip} for n, ip in ips.items()}},
            "HostConfig": {"NetworkMode": "bridge"},
            "State": state or {"Status": status},
        }


def _make_service(monkeypatch, available=True, containers=None, gateway="172.17.0.1"):
    service = docker_service_module.DockerService.__new__(docker_service_module.DockerService)
    service._is_available = available
    service.client = MagicMock() if available else None
    service.host_ips = set()

    if available:
        container_mock = MagicMock()
        container_mock.list.return_value = containers or []
        service.client.containers = container_mock

        if gateway is not None:
            net = MagicMock()
            net.attrs = {"IPAM": {"Config": [{"Gateway": gateway}]}}
            service.client.networks.get.return_value = net
    return service


def test_init_no_socket(monkeypatch):
    monkeypatch.setattr(docker_service_module.os.path, "exists", lambda p: False)
    service = docker_service_module.DockerService()
    assert service._is_available is False
    assert service.is_available() is False


def test_init_socket_but_connection_fails(monkeypatch):
    monkeypatch.setattr(docker_service_module.os.path, "exists", lambda p: True)

    def fake_client(**kwargs):
        raise RuntimeError("socket denied")

    monkeypatch.setattr(docker_service_module.docker, "DockerClient", fake_client)
    service = docker_service_module.DockerService()
    assert service.is_available() is False


def test_init_success(monkeypatch):
    monkeypatch.setattr(docker_service_module.os.path, "exists", lambda p: True)

    client = MagicMock()
    client.ping.return_value = None
    monkeypatch.setattr(docker_service_module.docker, "DockerClient", lambda **kw: client)

    service = docker_service_module.DockerService()
    assert service.is_available() is True
    assert service.client is client


def test_get_local_containers_when_unavailable():
    service = _make_service(monkeypatch={}, available=False)
    assert service.get_local_containers() == []


def test_get_local_containers_parses_ips(monkeypatch):
    containers = [
        FakeContainer("abc123", "web", "running", {"bridge": "172.17.0.2"}),
        FakeContainer("def456", "db", "exited", {"bridge": "172.17.0.3"}),
    ]
    service = _make_service(monkeypatch, containers=containers)

    result = service.get_local_containers()
    assert len(result) == 2
    assert result[0] == {
        "id": "abc123",
        "name": "web",
        "ips": ["172.17.0.2"],
        "status": "running",
        "image": "latest",
        "state": {"Status": "running"},
    }
    assert result[1]["name"] == "db"
    assert result[1]["status"] == "exited"


def test_get_local_containers_multiple_networks(monkeypatch):
    container = FakeContainer(
        "abc123", "web", "running",
        {"bridge": "172.17.0.2", "macvlan": "192.168.1.50"},
    )
    service = _make_service(monkeypatch, containers=[container])
    result = service.get_local_containers()
    assert result[0]["ips"] == ["172.17.0.2", "192.168.1.50"]


def test_get_local_containers_error_returns_empty(monkeypatch):
    service = _make_service(monkeypatch, containers=[])

    def boom():
        raise RuntimeError("docker daemon gone")

    service.client.containers.list = boom
    assert service.get_local_containers() == []


def test_get_container_status_by_ip(monkeypatch):
    containers = [
        FakeContainer("abc123", "web", "running", {"bridge": "172.17.0.2"}),
    ]
    service = _make_service(monkeypatch, containers=containers)
    assert service.get_container_status_by_ip("172.17.0.2") == "running"
    assert service.get_container_status_by_ip("10.0.0.99") is None


def test_get_bridge_gateway(monkeypatch):
    service = _make_service(monkeypatch, gateway="172.17.0.1")
    assert service.get_bridge_gateway() == "172.17.0.1"


def test_get_bridge_gateway_unavailable():
    service = _make_service(monkeypatch={}, available=False)
    assert service.get_bridge_gateway() is None


def test_get_bridge_gateway_error(monkeypatch):
    service = _make_service(monkeypatch, gateway=None)
    service.client.networks.get.side_effect = RuntimeError("no bridge")
    assert service.get_bridge_gateway() is None


def test_singleton_instance():
    assert isinstance(docker_service_module.docker_service, docker_service_module.DockerService)
