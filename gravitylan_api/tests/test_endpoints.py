from unittest.mock import patch, MagicMock
from gravitylan_api import GravityLANClient


@patch("gravitylan_api.client.GravityLANClient._request")
def test_agents_overview(mock_request):
    """Test agents.overview() resource method."""
    mock_request.return_value = {"agents": []}
    client = GravityLANClient(token="test")
    
    res = client.agents.overview()
    assert res == {"agents": []}
    mock_request.assert_called_once_with("GET", "/api/agent/overview")


@patch("gravitylan_api.client.GravityLANClient._request")
def test_devices_endpoints(mock_request):
    """Test devices resource list, get, and refresh_info methods."""
    client = GravityLANClient(token="test")

    # devices.list() without arguments
    mock_request.return_value = []
    res = client.devices.list()
    assert res == []
    mock_request.assert_called_with("GET", "/api/devices", params={"include_hidden": "false"})

    # devices.list() with arguments
    client.devices.list(include_hidden=True, group_id=4)
    mock_request.assert_called_with("GET", "/api/devices", params={"include_hidden": "true", "group_id": "4"})

    # devices.get()
    mock_request.return_value = {"id": 5}
    res = client.devices.get(5)
    assert res == {"id": 5}
    mock_request.assert_called_with("GET", "/api/devices/5")

    # devices.refresh_info()
    mock_request.return_value = {"status": "success"}
    res = client.devices.refresh_info(5)
    assert res == {"status": "success"}
    mock_request.assert_called_with("POST", "/api/devices/5/refresh-info")


@patch("gravitylan_api.client.GravityLANClient._request")
def test_topology_endpoints(mock_request):
    """Test topology.map() resource method."""
    mock_request.return_value = {"devices": []}
    client = GravityLANClient(token="test")

    res = client.topology.map()
    assert res == {"devices": []}
    mock_request.assert_called_once_with("GET", "/api/topology/map")


@patch("gravitylan_api.client.GravityLANClient._request")
def test_network_endpoints(mock_request):
    """Test network resource list_subnets and create_subnet methods."""
    client = GravityLANClient(token="test")

    # list_subnets()
    mock_request.return_value = []
    res = client.network.list_subnets()
    assert res == []
    mock_request.assert_called_with("GET", "/api/network/subnets")

    # create_subnet()
    mock_request.return_value = {"id": 1}
    res = client.network.create_subnet("192.168.1.0/24", "Main Subnet", dns_server="1.1.1.1")
    assert res == {"id": 1}
    mock_request.assert_called_with(
        "POST",
        "/api/network/subnets",
        json={
            "cidr": "192.168.1.0/24",
            "name": "Main Subnet",
            "dns_server": "1.1.1.1",
            "is_enabled": True,
        },
    )


@patch("gravitylan_api.client.GravityLANClient._request")
def test_backup_endpoints(mock_request):
    """Test backup.export() resource method."""
    mock_request.return_value = {"devices": []}
    client = GravityLANClient(token="test")

    res = client.backup.export()
    assert res == {"devices": []}
    mock_request.assert_called_once_with("GET", "/api/backup/export")


@patch("gravitylan_api.client.GravityLANClient._request")
def test_auth_endpoints(mock_request):
    """Test auth.login, logout, and check resource methods."""
    client = GravityLANClient(token="test")

    # auth.login()
    mock_request.return_value = {"status": "ok"}
    res = client.auth.login("password123")
    assert res == {"status": "ok"}
    mock_request.assert_called_with("POST", "/api/auth/login", json={"password": "password123"})

    # auth.logout()
    client.auth.logout()
    mock_request.assert_called_with("POST", "/api/auth/logout")

    # auth.check()
    client.auth.check()
    mock_request.assert_called_with("POST", "/api/auth/check")
