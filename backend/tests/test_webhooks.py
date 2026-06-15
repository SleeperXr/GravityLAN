import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from app.models.webhook import WebhookSubscription
from app.services.webhook_service import trigger_webhooks, _dispatch_webhooks

@pytest.mark.asyncio
async def test_webhooks_api_and_dispatch(client, db, admin_token):
    # 1. Register a webhook subscription
    create_payload = {
        "url": "http://127.0.0.1:9000/webhook-test",
        "events": ["scan.complete", "device.offline"]
    }
    response = await client.post(
        "/api/webhooks",
        json=create_payload,
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    created_data = response.json()
    assert created_data["url"] == "http://127.0.0.1:9000/webhook-test"
    assert created_data["events"] == ["scan.complete", "device.offline"]

    # 2. Get list of webhooks
    response = await client.get(
        "/api/webhooks",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    subs = response.json()
    assert len(subs) == 1
    assert subs[0]["id"] == created_data["id"]

    # 3. Trigger webhook dispatch and verify HTTP post mock
    class SessionContext:
        def __init__(self, session):
            self.session = session
        async def __aenter__(self):
            return self.session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    session_ctx = SessionContext(db)
    with patch("app.services.webhook_service.async_session", return_value=session_ctx):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            # Mock successful response
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            # Execute direct dispatch implementation so we can await it cleanly
            await _dispatch_webhooks("scan.complete", {"status": "finished"})

            # Assert post was called with correct arguments
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == "http://127.0.0.1:9000/webhook-test"
            payload = kwargs["json"]
            assert payload["event"] == "scan.complete"
            assert payload["data"] == {"status": "finished"}

    # 4. Invalidate subscription/Delete webhook
    response = await client.delete(
        f"/api/webhooks/{created_data['id']}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
