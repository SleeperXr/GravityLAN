import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from app.models.device import DeviceGroup, Device
from app.models.webhook import WebhookSubscription
from sqlalchemy import select

@pytest.mark.asyncio
async def test_chatbot_api_endpoints(client, db, admin_token):
    # Setup setup status complete and master settings
    from app.models.setting import Setting
    
    # 1. Test GET /api/auth/me with admin token
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert response.json() == {"scopes": ["*"]}

    # 2. Test GET /api/auth/me with scoped token
    create_payload = {
        "name": "Introspection Test PAT",
        "scopes": ["devices:read", "topology:read"]
    }
    response = await client.post(
        "/api/auth/tokens",
        json=create_payload,
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    pat_token = response.json()["token"]
    
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {pat_token}"}
    )
    assert response.status_code == 200
    assert response.json() == {"scopes": ["devices:read", "topology:read"]}

    # 3. Test GET /api/agents
    response = await client.get(
        "/api/agents",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert "agents" in response.json()

    # 4. Test GET /api/issues
    response = await client.get(
        "/api/issues",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)

    # 5. Test GET /api/topology/nodes and /api/topology/edges
    response = await client.get(
        "/api/topology/nodes",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)

    response = await client.get(
        "/api/topology/edges",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)

    # 6. Test GET /api/logs
    # Write a test log
    import logging
    logger = logging.getLogger("test_logger")
    logger.error("TEST LOG MESSAGE FOR CHATBOT AUDIT")
    
    response = await client.get(
        "/api/logs?limit=5",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    logs_list = response.json()
    assert isinstance(logs_list, list)
    
    # Exclude scoped token from accessing /api/logs if it lacks scope
    response = await client.get(
        "/api/logs",
        headers={"Authorization": f"Bearer {pat_token}"}
    )
    assert response.status_code == 403

    # 7. Test POST /api/webhooks/test
    # Register a webhook
    db_webhook = WebhookSubscription(url="http://127.0.0.1:9500/mock", events="test.event", is_active=True)
    db.add(db_webhook)
    await db.commit()
    
    # Session context patch for background tasks
    class SessionContext:
        def __init__(self, session):
            self.session = session
        async def __aenter__(self):
            return self.session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    session_ctx = SessionContext(db)
    with patch("app.services.webhook_service.async_session", return_value=session_ctx):
        with patch("app.services.webhook_service._send_webhook_post", new_callable=AsyncMock) as mock_send:
            response = await client.post(
                "/api/webhooks/test",
                json={"event": "test.event", "data": {"status": "ok"}},
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            
            # Wait briefly to allow background task to execute
            await asyncio.sleep(0.1)
            mock_send.assert_called_once()
            args, kwargs = mock_send.call_args
            assert args[1] == "http://127.0.0.1:9500/mock"
            assert args[2]["event"] == "test.event"
            assert args[2]["data"] == {"status": "ok"}

    # 8. Test GET /api/groups/{id}
    # Create group & device
    group = DeviceGroup(name="Testing Group", icon="server", color="#ffffff")
    db.add(group)
    await db.commit()
    await db.refresh(group)
    
    device = Device(ip="192.168.100.99", display_name="Test Dev", device_type="server", group_id=group.id)
    db.add(device)
    await db.commit()
    await db.refresh(group)
    
    response = await client.get(
        f"/api/groups/{group.id}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    group_data = response.json()
    assert group_data["name"] == "Testing Group"
    assert len(group_data["devices"]) == 1
    assert group_data["devices"][0]["ip"] == "192.168.100.99"

    # 9. Test GET /api/agents/{device_id}
    response = await client.get(
        f"/api/agents/{device.id}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert response.json()["device_id"] == device.id
    assert response.json()["is_installed"] is False

    # 10. Test GET /api/webhooks/test (with configured webhooks)
    # Re-register a webhook since we need one for GET test
    db_webhook_get = WebhookSubscription(url="http://127.0.0.1:9500/mock-get", events="test.event", is_active=True)
    db.add(db_webhook_get)
    await db.commit()

    session_ctx = SessionContext(db)
    with patch("app.services.webhook_service.async_session", return_value=session_ctx):
        with patch("app.services.webhook_service._send_webhook_post", new_callable=AsyncMock) as mock_send:
            response = await client.get(
                "/api/webhooks/test",
                headers={"Authorization": f"Bearer {admin_token}"}
            )
            assert response.status_code == 200
            assert "scheduled for dispatch via GET" in response.json()["message"]

    # Delete the webhooks to verify the 404 error
    await db.delete(db_webhook)
    await db.delete(db_webhook_get)
    await db.commit()
    response = await client.get(
        "/api/webhooks/test",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 404

    # 11. Test GET /api/scan-profiles
    response = await client.get(
        "/api/scan-profiles",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    profiles = response.json()
    assert isinstance(profiles, list)
    assert len(profiles) == 3
    assert profiles[0]["name"] == "Standard Discovery"

    # 12. Test GET /api/notifications
    from app.models.device import DeviceHistory
    # Add a device offline history entry
    hist = DeviceHistory(device_id=device.id, status="offline", message="Device went offline")
    db.add(hist)
    await db.commit()

    response = await client.get(
        "/api/notifications",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    notifications = response.json()
    assert len(notifications) >= 1
    assert notifications[0]["title"] == "🔴 Gerät offline"
    assert notifications[0]["type"] == "warning"

