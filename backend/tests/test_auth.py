import pytest
from app.models.setting import Setting
from sqlalchemy import select

@pytest.mark.asyncio
async def test_full_auth_flow(client, db):
    """Test the complete authentication lifecycle using cookies."""
    
    # 1. Setup credentials in the test DB
    password = "testpassword123"
    token = "test-token-xyz"
    db.add(Setting(key="api.admin_password", value=password))
    db.add(Setting(key="api.master_token", value=token))
    await db.commit()

    # 2. Try accessing protected endpoint (should fail)
    response = await client.get("/api/settings")
    assert response.status_code == 401

    # 3. Login
    login_res = await client.post("/api/auth/login", json={"password": password})
    assert login_res.status_code == 200
    
    # 4. Access protected endpoint WITH cookie
    settings_res = await client.get("/api/settings")
    assert settings_res.status_code == 200
    
    # 5. Logout
    logout_res = await client.post("/api/auth/logout")
    assert logout_res.status_code == 200
    
    # 6. Verify access is denied again
    final_res = await client.get("/api/settings")
    assert final_res.status_code == 401

@pytest.mark.asyncio
async def test_login_invalid_password(client, db):
    """Verify that wrong password doesn't grant access."""
    db.add(Setting(key="api.admin_password", value="secret"))
    db.add(Setting(key="api.master_token", value="some-token"))
    await db.commit()

    login_res = await client.post("/api/auth/login", json={"password": "wrongpassword"})
    assert login_res.status_code == 401
