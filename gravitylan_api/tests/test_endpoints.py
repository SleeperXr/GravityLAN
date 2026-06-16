from unittest.mock import patch, MagicMock
from gravitylan_api import GravityLANClient


@patch("gravitylan_api.client.GravityLANClient._request")
def test_agents_overview(mock_request):
    """Test agents.overview(), agents.list(), and agents.get() resource methods."""
    mock_request.return_value = {"agents": []}
    client = GravityLANClient(token="test")
    
    res = client.agents.overview()
    assert res == {"agents": []}
    mock_request.assert_called_with("GET", "/api/agent/overview")

    res = client.agents.list()
    assert res == {"agents": []}
    mock_request.assert_called_with("GET", "/api/agents")

    mock_request.return_value = {"device_id": 10, "is_active": True}
    res = client.agents.get(10)
    assert res == {"device_id": 10, "is_active": True}
    mock_request.assert_called_with("GET", "/api/agents/10")


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

    # devices.get_group()
    mock_request.return_value = {"id": 1, "devices": []}
    res = client.devices.get_group(1)
    assert res == {"id": 1, "devices": []}
    mock_request.assert_called_with("GET", "/api/groups/1")

    # devices.list_issues()
    mock_request.return_value = []
    res = client.devices.list_issues()
    assert res == []
    mock_request.assert_called_with("GET", "/api/issues", params={})

    client.devices.list_issues(device_id=14, type="service_down")
    mock_request.assert_called_with("GET", "/api/issues", params={"device_id": "14", "type": "service_down"})

    # devices.list_notifications()
    mock_request.return_value = []
    res = client.devices.list_notifications()
    assert res == []
    mock_request.assert_called_with("GET", "/api/notifications", params={})

    client.devices.list_notifications(since="2026-06-16T10:00:00Z", unread=True, device_id=12)
    mock_request.assert_called_with(
        "GET",
        "/api/notifications",
        params={"since": "2026-06-16T10:00:00Z", "unread": "true", "device_id": "12"}
    )


@patch("gravitylan_api.client.GravityLANClient._request")
def test_topology_endpoints(mock_request):
    """Test topology.map(), topology.nodes(), and topology.edges() resource methods."""
    mock_request.return_value = {"devices": []}
    client = GravityLANClient(token="test")

    res = client.topology.map()
    assert res == {"devices": []}
    mock_request.assert_called_with("GET", "/api/topology/map")

    mock_request.return_value = []
    res = client.topology.nodes()
    assert res == []
    mock_request.assert_called_with("GET", "/api/topology/nodes")

    res = client.topology.edges()
    assert res == []
    mock_request.assert_called_with("GET", "/api/topology/edges")


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

    # auth.me()
    mock_request.return_value = {"scopes": ["*"]}
    res = client.auth.me()
    assert res == {"scopes": ["*"]}
    mock_request.assert_called_with("GET", "/api/auth/me")

    # auth.logs()
    mock_request.return_value = []
    res = client.auth.logs(limit=10, level="ERROR")
    assert res == []
    mock_request.assert_called_with("GET", "/api/logs", params={"limit": 10, "level": "ERROR"})


@patch("gravitylan_api.client.GravityLANClient._request")
def test_scan_profiles_endpoints(mock_request):
    """Test scan_profiles.list() resource method."""
    mock_request.return_value = []
    client = GravityLANClient(token="test")

    res = client.scan_profiles.list()
    assert res == []
    mock_request.assert_called_with("GET", "/api/scan-profiles")


@patch("gravitylan_api.client.GravityLANClient._request")
def test_health_endpoints(mock_request):
    """Test health.summary() resource method."""
    mock_request.return_value = {"api_version": "0.3.0"}
    client = GravityLANClient(token="test")

    res = client.health.summary()
    assert res == {"api_version": "0.3.0"}
    mock_request.assert_called_with("GET", "/api/health/summary")
