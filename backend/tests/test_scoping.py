import pytest
from app.models.api_token import ApiToken
from sqlalchemy import select

@pytest.mark.asyncio
async def test_scoped_tokens_permissions(client, db, admin_token):
    # 1. Create a scoped API Token
    create_payload = {
        "name": "Home Assistant Scoped",
        "scopes": ["devices:read", "topology:read"]
    }
    response = await client.post(
        "/api/auth/tokens",
        json=create_payload,
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    created_data = response.json()
    assert created_data["name"] == "Home Assistant Scoped"
    assert created_data["scopes"] == ["devices:read", "topology:read"]
    plaintext_token = created_data["token"]

    # 2. Test permitted GET device access (has devices:read)
    response = await client.get(
        "/api/devices",
        headers={"Authorization": f"Bearer {plaintext_token}"}
    )
    assert response.status_code == 200

    # 3. Test permitted GET topology map access (has topology:read)
    response = await client.get(
        "/api/topology/map",
        headers={"Authorization": f"Bearer {plaintext_token}"}
    )
    assert response.status_code == 200

    # 4. Test blocked GET settings (lacks settings:read)
    response = await client.get(
        "/api/settings",
        headers={"Authorization": f"Bearer {plaintext_token}"}
    )
    assert response.status_code == 403
    assert "Token is missing the required scope 'settings:read'" in response.json()["detail"]

    # 5. Test blocked POST to devices/groups (lacks devices:write)
    response = await client.post(
        "/api/groups",
        json={"name": "Test Group"},
        headers={"Authorization": f"Bearer {plaintext_token}"}
    )
    assert response.status_code == 403
    assert "Read-only token cannot perform state-modifying actions" in response.json()["detail"]
