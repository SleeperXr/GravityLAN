import os
from unittest.mock import patch, MagicMock
import pytest
import requests

from gravitylan_api import (
    GravityLANClient,
    GravityLANAuthError,
    GravityLANConnectionError,
    GravityLANHTTPError,
)


def test_client_init_defaults():
    """Test client initialization using default values and environment variables."""
    with patch.dict(os.environ, {"GRAVITYLAN_BASE_URL": "http://env-url:8000", "GRAVITYLAN_TOKEN": "env-token"}):
        client = GravityLANClient()
        assert client.base_url == "http://env-url:8000"
        assert client.token == "env-token"
        assert client.session.headers["Authorization"] == "Bearer env-token"


def test_client_init_args():
    """Test client initialization passing direct arguments."""
    client = GravityLANClient(base_url="http://arg-url:9000", token="arg-token")
    assert client.base_url == "http://arg-url:9000"
    assert client.token == "arg-token"
    assert client.session.headers["Authorization"] == "Bearer arg-token"


@patch("requests.Session.request")
def test_client_request_success(mock_request):
    """Test successful request parsing."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.ok = True
    mock_response.content = b'{"status": "ok"}'
    mock_response.json.return_value = {"status": "ok"}
    mock_request.return_value = mock_response

    client = GravityLANClient(token="my-token")
    res = client._request("GET", "/api/test")
    assert res == {"status": "ok"}
    mock_request.assert_called_once_with(
        method="GET",
        url="http://localhost:8000/api/test",
        params=None,
        json=None,
        timeout=10.0,
    )


@patch("requests.Session.request")
def test_client_request_http_error(mock_request):
    """Test API non-2xx response raised as GravityLANHTTPError."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.ok = False
    mock_response.json.return_value = {"detail": "Device not found"}
    mock_request.return_value = mock_response

    client = GravityLANClient(token="my-token")
    with pytest.raises(GravityLANHTTPError) as exc_info:
        client._request("GET", "/api/devices/999")
    assert exc_info.value.status_code == 404
    assert "Device not found" in exc_info.value.message


@patch("requests.Session.request")
@patch("time.sleep")
def test_client_request_retry_and_failure(mock_sleep, mock_request):
    """Test request retry and final conversion to GravityLANConnectionError."""
    mock_request.side_effect = requests.exceptions.Timeout("Connection timed out")

    client = GravityLANClient(token="my-token")
    with pytest.raises(GravityLANConnectionError) as exc_info:
        client._request("GET", "/api/test")
    
    assert mock_request.call_count == 3
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(2)
    mock_sleep.assert_any_call(4)
    assert "Connection timed out" in str(exc_info.value)


@patch("requests.Session.post")
@patch("requests.Session.request")
def test_client_password_login_flow(mock_request, mock_post):
    """Test session cookie login flow when password is provided."""
    # Mock successful login
    mock_login_resp = MagicMock()
    mock_login_resp.status_code = 200
    mock_login_resp.ok = True
    mock_login_resp.json.return_value = {"status": "ok"}
    mock_post.return_value = mock_login_resp

    # Mock normal request
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.ok = True
    mock_resp.content = b'{"data": "success"}'
    mock_resp.json.return_value = {"data": "success"}
    mock_request.return_value = mock_resp

    client = GravityLANClient(password="admin123")
    
    # 1. Trigger request. Should trigger login first since no session cookie is set
    res = client._request("GET", "/api/test")
    assert res == {"data": "success"}

    # Mock cookies mapping to represent a session cookie is now present
    client.session.cookies.set("gravitylan_token", "session_abc123")

    # 2. Trigger another request. Should NOT trigger login again
    res2 = client._request("GET", "/api/test")
    assert res2 == {"data": "success"}
    
    mock_post.assert_called_once_with(
        "http://localhost:8000/api/auth/login",
        json={"password": "admin123"},
        timeout=10.0,
    )
