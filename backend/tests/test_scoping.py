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

    # 6. Active GET scanner routes (scan-ip, live-discovery) require scanner:start even with scanner:read
    create_scanner_ro = await client.post(
        "/api/auth/tokens",
        json={"name": "Scanner ReadOnly", "scopes": ["scanner:read", "devices:read"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_scanner_ro.status_code == 200
    ro_tok = create_scanner_ro.json()["token"]

    for active_get in ("/api/scanner/scan-ip?ip=192.168.1.1", "/api/scanner/live-discovery?subnets=192.168.1.0/24"):
        res = await client.get(active_get, headers={"Authorization": f"Bearer {ro_tok}"})
        assert res.status_code == 403
        assert "scanner:start" in res.json()["detail"]

    # 7. /api/interfaces routes enforce devices:read / devices:write scopes
    res_suggestions = await client.get("/api/interfaces/suggestions", headers={"Authorization": f"Bearer {ro_tok}"})
    assert res_suggestions.status_code == 200

    res_dismiss = await client.post(
        "/api/interfaces/suggestions/dismiss",
        json={"target_id": 1, "kind": "device", "candidate_ip": "192.168.1.2"},
        headers={"Authorization": f"Bearer {ro_tok}"},
    )
    assert res_dismiss.status_code == 403
    assert "devices:write" in res_dismiss.json()["detail"]
