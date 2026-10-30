import pytest

@pytest.mark.asyncio
async def test_health_check(client, monkeypatch, tmp_path):
    """Verify that the backend is alive: without a frontend build, / answers with its status."""
    import app.main as main
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path)
    monkeypatch.setattr(main, "_resolve_frontend_vue_dir", lambda: tmp_path)
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
    assert data["agent_version"]  # the About page shows it

@pytest.mark.asyncio
async def test_unauthorized_access(client, db):
    """Verify that protected endpoints return 401 without auth."""
    from app.models.setting import Setting
    db.add(Setting(key="setup.complete", value="true"))
    db.add(Setting(key="api.master_token", value="some-token"))
    await db.commit()
    # Settings should be protected by get_current_admin
    response = await client.get("/api/settings")
    assert response.status_code == 401
