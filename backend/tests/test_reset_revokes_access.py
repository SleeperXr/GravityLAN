"""A database reset revokes every credential of the old setup (#48)."""
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.models.api_token import ApiToken
from app.models.ssh import SshKey, SshKnownHost, SshProfile
from app.models.webhook import WebhookSubscription
from app.services.enrollment_service import enrollment_store
from app.services.session_service import session_store

HEADERS = {"Authorization": "Bearer test-admin-token-12345"}


@pytest.fixture(autouse=True)
def no_scheduler(monkeypatch):
    from app.scanner.scheduler import scheduler

    monkeypatch.setattr(scheduler, "stop", AsyncMock())
    monkeypatch.setattr(scheduler, "start", AsyncMock())


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


@pytest.mark.asyncio
async def test_reset_revokes_tokens_sessions_keys_and_webhooks(client, db, admin_token):
    res = await client.post("/api/auth/tokens", json={"name": "leaked", "scopes": ["devices:read"]}, headers=HEADERS)
    leaked_token = res.json()["token"]
    key = SshKey(name="k", key_type="ssh-ed25519", fingerprint="SHA256:k", public_key="ssh-ed25519 AAAA",
                 encrypted_private_key="x")
    db.add(key)
    await db.flush()
    db.add_all([
        SshProfile(name="p", host="10.0.0.1", port=22, username="root", auth_method="key", key_id=key.id),
        SshKnownHost(host="10.0.0.1", port=22, key_type="ssh-ed25519", fingerprint="SHA256:h", public_key="x"),
        WebhookSubscription(url="http://hook.example/x", events="device.offline"),
    ])
    await db.commit()
    old_session = session_store.create_session(user_agent=None)
    old_code = enrollment_store.issue(1)

    res = await client.post("/api/settings/reset-db", headers=HEADERS)
    assert res.status_code == 200, res.text

    db.expire_all()
    for model in (ApiToken, SshKey, SshProfile, SshKnownHost, WebhookSubscription):
        assert await _count(db, model) == 0, model.__tablename__
    assert session_store.get_session(old_session) is None
    assert not enrollment_store.is_valid(old_code, 1)

    # Setup again with a new password: the old token stays dead
    res = await client.post("/api/setup/complete", json={"admin_password": "new-password-123"})
    assert res.status_code == 200
    client.cookies.clear()
    res = await client.get("/api/devices", headers={"Authorization": f"Bearer {leaked_token}"})
    assert res.status_code == 401


class _FakeSocket:
    def __init__(self):
        self.closed_with = None

    async def close(self, code: int = 1000, reason: str | None = None):
        self.closed_with = code

    async def send_text(self, text: str):
        pass

    async def send_json(self, data):
        pass


@pytest.mark.asyncio
async def test_reset_closes_open_log_scan_and_metric_streams(client, admin_token, monkeypatch):
    # These streams authenticate once when they open: logging sessions out does not reach them
    from app.api.scanner import state as scan_state
    from app.services.agent_telemetry import _ws_subscribers
    from app.services.log_streamer import log_handler

    log_stream, scan_stream, metric_stream = _FakeSocket(), _FakeSocket(), _FakeSocket()
    log_handler.subscribe(log_stream)
    await scan_state.add_client(scan_stream)
    monkeypatch.setitem(_ws_subscribers, 7, {metric_stream})

    res = await client.post("/api/settings/reset-db", headers=HEADERS)
    assert res.status_code == 200, res.text

    assert [s.closed_with for s in (log_stream, scan_stream, metric_stream)] == [4003, 4003, 4003]
    assert log_stream not in log_handler.subscribers
    assert scan_stream not in scan_state.ws_clients
    assert 7 not in _ws_subscribers


@pytest.mark.asyncio
async def test_a_stalled_stream_does_not_hold_up_the_revocation(monkeypatch):
    import asyncio

    from app.services import stream_revocation
    from app.services.agent_telemetry import _ws_subscribers

    class _Stalled(_FakeSocket):
        async def close(self, code: int = 1000, reason: str | None = None):
            await asyncio.sleep(60)

    answering = _FakeSocket()
    monkeypatch.setattr(stream_revocation, "CLOSE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setitem(_ws_subscribers, 8, {_Stalled(), answering})

    closed = await asyncio.wait_for(stream_revocation.close_metric_streams([8]), timeout=5)

    assert closed == 1 and answering.closed_with == 4003
    assert 8 not in _ws_subscribers
