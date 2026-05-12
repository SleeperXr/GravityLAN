import pytest

@pytest.mark.asyncio
async def test_health_check(client):
    """Verify that the backend is alive."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "GravityLAN"
    assert data["status"] == "online"

@pytest.mark.asyncio
async def test_setup_status_unauthorized(client):
    """Verify that setup/status is accessible without auth (initial state)."""
    response = await client.get("/api/setup/status")
    assert response.status_code == 200
    data = response.json()
    assert "is_setup_complete" in data

@pytest.mark.asyncio
async def test_unauthorized_access(client):
    """Verify that protected endpoints return 401 without auth."""
    # Settings should be protected by get_current_admin
    response = await client.get("/api/settings")
    assert response.status_code == 401
