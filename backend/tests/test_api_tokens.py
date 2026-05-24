import pytest
from app.models.api_token import ApiToken
from sqlalchemy import select

@pytest.mark.asyncio
async def test_api_token_lifecycle_and_permissions(client, db, admin_token):
    # 1. Create a new API Token (must use admin credentials)
    create_payload = {"name": "Home Assistant integration"}
    response = await client.post(
        "/api/auth/tokens",
        json=create_payload,
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    created_data = response.json()
    assert created_data["name"] == "Home Assistant integration"
    assert created_data["prefix"].startswith("gl_pat_")
    assert "token" in created_data
    plaintext_token = created_data["token"]

    # 2. List tokens (must be admin)
    response = await client.get(
        "/api/auth/tokens",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    tokens_list = response.json()
    assert len(tokens_list) == 1
    assert tokens_list[0]["id"] == created_data["id"]
    assert "token" not in tokens_list[0]  # The plaintext token must NOT be in the list response!

    # 3. Test read-only GET access using the API Token
    # Let's hit GET /api/devices (protected by admin in routers, but should bypass for read-only tokens)
    response = await client.get(
        "/api/devices",
        headers={"Authorization": f"Bearer {plaintext_token}"}
    )
    assert response.status_code == 200

    # 4. Test blocked write access (POST request must fail with 403)
    response = await client.post(
        "/api/groups",
        json={"name": "New Group", "icon": "folder"},
        headers={"Authorization": f"Bearer {plaintext_token}"}
    )
    assert response.status_code == 403
    assert "Read-only token cannot perform state-modifying actions" in response.json()["detail"]

    # 5. Test blocked sensitive GET routes
    response = await client.get(
        "/api/backup/export",
        headers={"Authorization": f"Bearer {plaintext_token}"}
    )
    assert response.status_code == 403
    assert "Read-only token is not authorized for this administrative action" in response.json()["detail"]

    # Read-only tokens must also be blocked from managing tokens
    response = await client.get(
        "/api/auth/tokens",
        headers={"Authorization": f"Bearer {plaintext_token}"}
    )
    assert response.status_code == 403

    # 6. Revoke (DELETE) the token (must use admin credentials)
    response = await client.delete(
        f"/api/auth/tokens/{created_data['id']}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200

    # 7. Check that the token is now invalid (401 Unauthorized)
    response = await client.get(
        "/api/devices",
        headers={"Authorization": f"Bearer {plaintext_token}"}
    )
    assert response.status_code == 401
