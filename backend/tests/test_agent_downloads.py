"""Tests for agent download / deploy / uninstall endpoints (app/api/agent.py).

These endpoints use the shared ``_detect_server_url`` helper and issue
SSH operations; the SSH boundary (``deploy_agent`` / ``remove_agent`` /
``agent_deployer``) is mocked so we test the HTTP contract + URL/script
generation, not real remote access.

The manual ``curl | sudo bash`` installer is authorised by a short-lived,
single-use enrollment code issued via ``POST /api/agent/enroll/{device_id}``;
the agent config (which carries the agent token) is never served without
either admin auth or such a code.
"""

import json

import pytest
from sqlalchemy import select

from app.models.device import Device
from app.models.agent import AgentToken
from app.models.setting import Setting


@pytest.fixture(autouse=True)
def clear_setting_cache():
    from datetime import datetime, timezone
    from app.api import agent as _agent
    _agent._setting_cache.clear()
    _agent._setting_cache_time = datetime.min.replace(tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clear_enrollment_codes():
    from app.services.enrollment_service import enrollment_store
    enrollment_store._codes.clear()
    yield
    enrollment_store._codes.clear()


def _admin_headers():
    return {"Authorization": "Bearer test-admin-token-12345"}


async def _seed_device(db, ip="192.168.1.50", device_id=None):
    device = Device(ip=ip, display_name=f"Dev {ip}", is_online=True)
    if device_id:
        device.id = device_id
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


async def _seed_server_url(db, monkeypatch):
    # server.url set -> _detect_server_url returns it without touching subnets
    db.add(Setting(key="server.url", value="http://gravity.example:9000"))
    await db.commit()
    monkeypatch.setattr("app.scanner.utils.get_local_subnets", None)


async def _enroll(client, device_id) -> str:
    response = await client.post(f"/api/agent/enroll/{device_id}", headers=_admin_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["expires_in"] > 0
    return body["code"]


async def _agent_token(db, device_id):
    return (await db.execute(select(AgentToken).where(AgentToken.device_id == device_id))).scalar_one_or_none()


# --- download/agent/config --------------------------------------------------

@pytest.mark.asyncio
async def test_download_agent_config_creates_token(client, db, admin_token, monkeypatch):
    device = await _seed_device(db)
    await _seed_server_url(db, monkeypatch)

    response = await client.get(f"/api/agent/download/config/{device.id}", headers=_admin_headers())
    assert response.status_code == 200
    config = json.loads(response.text)
    assert config["device_id"] == device.id
    assert config["server_url"] == "http://gravity.example:9000"
    assert config["interval"] == 30

    # token was created and persisted
    token_obj = await _agent_token(db, device.id)
    assert token_obj is not None
    assert token_obj.token == config["token"]


@pytest.mark.asyncio
async def test_download_agent_config_reuses_token(client, db, admin_token, monkeypatch):
    device = await _seed_device(db)
    db.add(AgentToken(device_id=device.id, token="existing-token-123", is_active=True))
    await _seed_server_url(db, monkeypatch)

    response = await client.get(f"/api/agent/download/config/{device.id}", headers=_admin_headers())
    assert response.status_code == 200
    config = json.loads(response.text)
    assert config["token"] == "existing-token-123"


@pytest.mark.asyncio
async def test_download_agent_config_404(client, db, admin_token):
    response = await client.get("/api/agent/download/config/9999", headers=_admin_headers())
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_download_agent_config_requires_auth(client, db, admin_token):
    """Anyone on the LAN could previously enumerate device ids and harvest agent tokens."""
    device = await _seed_device(db)

    response = await client.get(f"/api/agent/download/config/{device.id}")
    assert response.status_code == 401
    assert await _agent_token(db, device.id) is None


@pytest.mark.asyncio
async def test_download_agent_config_rejects_unknown_code(client, db, admin_token):
    device = await _seed_device(db)

    response = await client.get(
        f"/api/agent/download/config/{device.id}", params={"code": "not-a-valid-code-123456"}
    )
    assert response.status_code == 403
    assert await _agent_token(db, device.id) is None


# --- enrollment codes -------------------------------------------------------

@pytest.mark.asyncio
async def test_enroll_requires_admin(client, db, admin_token):
    device = await _seed_device(db)
    response = await client.post(f"/api/agent/enroll/{device.id}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_enroll_unknown_device_404(client, db, admin_token):
    response = await client.post("/api/agent/enroll/9999", headers=_admin_headers())
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_enrollment_code_unlocks_config_once(client, db, admin_token, monkeypatch):
    device = await _seed_device(db)
    await _seed_server_url(db, monkeypatch)
    code = await _enroll(client, device.id)

    first = await client.get(f"/api/agent/download/config/{device.id}", params={"code": code})
    assert first.status_code == 200
    assert json.loads(first.text)["token"] == (await _agent_token(db, device.id)).token

    second = await client.get(f"/api/agent/download/config/{device.id}", params={"code": code})
    assert second.status_code == 403


@pytest.mark.asyncio
async def test_enrollment_code_is_bound_to_device(client, db, admin_token):
    device_a = await _seed_device(db, ip="192.168.1.50")
    device_b = await _seed_device(db, ip="192.168.1.51")
    code = await _enroll(client, device_a.id)

    response = await client.get(f"/api/agent/download/config/{device_b.id}", params={"code": code})
    assert response.status_code == 403
    assert await _agent_token(db, device_b.id) is None


def test_enrollment_code_expires():
    from app.services.enrollment_service import EnrollmentStore

    now = [1000.0]
    store = EnrollmentStore(ttl_seconds=60, clock=lambda: now[0])
    code = store.issue(device_id=1)

    assert store.is_valid(code, 1)
    now[0] += 61
    assert not store.is_valid(code, 1)
    assert not store.consume(code, 1)


# --- download/install-sh ----------------------------------------------------

@pytest.mark.asyncio
async def test_download_install_script_contains_url_id_and_code(client, db, admin_token, monkeypatch):
    device = await _seed_device(db)
    await _seed_server_url(db, monkeypatch)
    code = await _enroll(client, device.id)

    response = await client.get(f"/api/agent/download/install-sh/{device.id}", params={"code": code})
    assert response.status_code == 200
    assert "text/x-sh" in response.headers.get("content-type", "").lower() or response.headers.get("content-type", "").startswith("text")
    assert 'SERVER_URL="http://gravity.example:9000"' in response.text
    assert f'DEVICE_ID="{device.id}"' in response.text
    assert f'ENROLL_CODE="{code}"' in response.text
    assert 'curl -fsSL "$SERVER_URL/api/agent/download/config/$DEVICE_ID?code=$ENROLL_CODE"' in response.text
    assert "gravitylan-agent.service" in response.text

    # Fetching the script itself must not use up the code the script needs next.
    config = await client.get(f"/api/agent/download/config/{device.id}", params={"code": code})
    assert config.status_code == 200


@pytest.mark.asyncio
async def test_download_install_script_without_code_is_rejected(client, db, admin_token):
    device = await _seed_device(db)

    response = await client.get(f"/api/agent/download/install-sh/{device.id}")
    assert response.status_code == 403
    # The body is a shell script that aborts, so `curl ... | sudo bash` prints a readable error.
    assert "exit 1" in response.text
    assert "SERVER_URL" not in response.text


@pytest.mark.asyncio
async def test_download_install_script_does_not_reflect_bad_code(client, db, admin_token):
    device = await _seed_device(db)
    evil = '"; rm -rf / #'

    response = await client.get(f"/api/agent/download/install-sh/{device.id}", params={"code": evil})
    assert response.status_code == 403
    assert evil not in response.text


@pytest.mark.asyncio
async def test_download_install_script_404(client, db, admin_token):
    from app.services.enrollment_service import enrollment_store

    code = enrollment_store.issue(device_id=9999)
    response = await client.get("/api/agent/download/install-sh/9999", params={"code": code})
    assert response.status_code == 404


# --- download/uninstall-sh --------------------------------------------------

@pytest.mark.asyncio
async def test_download_uninstall_script(client, db):
    device = await _seed_device(db)
    response = await client.get(f"/api/agent/download/uninstall-sh/{device.id}", headers=_admin_headers())
    assert response.status_code == 200
    assert "systemctl stop gravitylan-agent.service" in response.text
    assert "rm -rf" in response.text


# --- deploy / uninstall -----------------------------------------------------

@pytest.mark.asyncio
async def test_deploy_agent_endpoint_success(client, db, admin_token, monkeypatch):
    device = await _seed_device(db)
    db.add(Setting(key="server.url", value="http://gravity.example:9000"))
    await db.commit()

    async def fake_deploy(**kwargs):
        return True, "Agent started successfully", "deployed-token-abc"

    monkeypatch.setattr("app.api.agent.deploy_agent", fake_deploy)

    response = await client.post(
        f"/api/agent/deploy/{device.id}",
        json={"ssh_user": "root", "ssh_password": "pw"},
        headers=_admin_headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert "Agent started successfully" in response.json()["message"]

    # token was persisted
    token_obj = await _agent_token(db, device.id)
    assert token_obj is not None
    assert token_obj.token == "deployed-token-abc"


@pytest.mark.asyncio
async def test_deploy_agent_endpoint_failure(client, db, admin_token, monkeypatch):
    device = await _seed_device(db)
    db.add(Setting(key="server.url", value="http://gravity.example:9000"))
    await db.commit()

    async def fake_deploy(**kwargs):
        return False, "SSH connection failed", ""

    monkeypatch.setattr("app.api.agent.deploy_agent", fake_deploy)

    response = await client.post(
        f"/api/agent/deploy/{device.id}",
        json={"ssh_user": "root", "ssh_password": "pw"},
        headers=_admin_headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_uninstall_agent_endpoint_success(client, db, admin_token, monkeypatch):
    device = await _seed_device(db)
    db.add(AgentToken(device_id=device.id, token="old-token", is_active=True))
    await db.commit()

    async def fake_remove(**kwargs):
        return True, "Agent removed"

    monkeypatch.setattr("app.api.agent.remove_agent", fake_remove)

    response = await client.post(
        f"/api/agent/uninstall/{device.id}",
        json={"ssh_user": "root", "ssh_password": "pw"},
        headers=_admin_headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    assert await _agent_token(db, device.id) is None  # token deactivated/deleted


@pytest.mark.asyncio
async def test_uninstall_agent_endpoint_failure(client, db, admin_token, monkeypatch):
    device = await _seed_device(db)
    db.add(AgentToken(device_id=device.id, token="old-token", is_active=True))
    await db.commit()

    async def fake_remove(**kwargs):
        return False, "SSH connection failed"

    monkeypatch.setattr("app.api.agent.remove_agent", fake_remove)

    response = await client.post(
        f"/api/agent/uninstall/{device.id}",
        json={"ssh_user": "root", "ssh_password": "pw"},
        headers=_admin_headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"

    # token preserved on failure
    assert await _agent_token(db, device.id) is not None
