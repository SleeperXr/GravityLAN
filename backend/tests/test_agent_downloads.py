"""Tests for agent download / deploy / uninstall endpoints (app/api/agent.py).

These endpoints use the shared ``_detect_server_url`` helper and issue
SSH operations; the SSH boundary (``deploy_agent`` / ``remove_agent`` /
``agent_deployer``) is mocked so we test the HTTP contract + URL/script
generation, not real remote access.
"""

import json

import pytest

from app.models.device import Device
from app.models.agent import AgentToken
from app.models.setting import Setting


@pytest.fixture(autouse=True)
def clear_setting_cache():
    from datetime import datetime, timezone
    from app.api import agent as _agent
    _agent._setting_cache.clear()
    _agent._setting_cache_time = datetime.min.replace(tzinfo=timezone.utc)


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


# --- download/agent/config --------------------------------------------------

@pytest.mark.asyncio
async def test_download_agent_config_creates_token(client, db, monkeypatch):
    device = await _seed_device(db)
    # server.url set -> _detect_server_url returns it without touching subnets
    db.add(Setting(key="server.url", value="http://gravity.example:9000"))
    await db.commit()

    monkeypatch.setattr("app.scanner.utils.get_local_subnets", None)

    response = await client.get(f"/api/agent/download/config/{device.id}", headers=_admin_headers())
    assert response.status_code == 200
    config = json.loads(response.text)
    assert config["device_id"] == device.id
    assert config["server_url"] == "http://gravity.example:9000"
    assert config["interval"] == 30

    # token was created and persisted
    from sqlalchemy import select
    token_obj = (await db.execute(select(AgentToken).where(AgentToken.device_id == device.id))).scalar_one_or_none()
    assert token_obj is not None
    assert token_obj.token == config["token"]


@pytest.mark.asyncio
async def test_download_agent_config_reuses_token(client, db, monkeypatch):
    device = await _seed_device(db)
    existing = AgentToken(device_id=device.id, token="existing-token-123", is_active=True)
    db.add(existing)
    db.add(Setting(key="server.url", value="http://gravity.example:9000"))
    await db.commit()

    monkeypatch.setattr("app.scanner.utils.get_local_subnets", None)

    response = await client.get(f"/api/agent/download/config/{device.id}", headers=_admin_headers())
    assert response.status_code == 200
    config = json.loads(response.text)
    assert config["token"] == "existing-token-123"


@pytest.mark.asyncio
async def test_download_agent_config_404(client, db):
    response = await client.get("/api/agent/download/config/9999", headers=_admin_headers())
    assert response.status_code == 404


# --- download/install-sh ----------------------------------------------------

@pytest.mark.asyncio
async def test_download_install_script_contains_url_and_id(client, db, monkeypatch):
    device = await _seed_device(db)
    db.add(Setting(key="server.url", value="http://gravity.example:9000"))
    await db.commit()

    monkeypatch.setattr("app.scanner.utils.get_local_subnets", None)

    response = await client.get(f"/api/agent/download/install-sh/{device.id}", headers=_admin_headers())
    assert response.status_code == 200
    assert "text/x-sh" in response.headers.get("content-type", "").lower() or response.headers.get("content-type", "").startswith("text")
    assert 'SERVER_URL="http://gravity.example:9000"' in response.text
    assert f'DEVICE_ID="{device.id}"' in response.text
    assert "gravitylan-agent.service" in response.text


@pytest.mark.asyncio
async def test_download_install_script_404(client, db):
    response = await client.get("/api/agent/download/install-sh/9999", headers=_admin_headers())
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
async def test_deploy_agent_endpoint_success(client, db, monkeypatch):
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
    from sqlalchemy import select
    token_obj = (await db.execute(select(AgentToken).where(AgentToken.device_id == device.id))).scalar_one_or_none()
    assert token_obj is not None
    assert token_obj.token == "deployed-token-abc"


@pytest.mark.asyncio
async def test_deploy_agent_endpoint_failure(client, db, monkeypatch):
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
async def test_uninstall_agent_endpoint_success(client, db, monkeypatch):
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

    from sqlalchemy import select
    token_obj = (await db.execute(select(AgentToken).where(AgentToken.device_id == device.id))).scalar_one_or_none()
    assert token_obj is None  # token deactivated/deleted


@pytest.mark.asyncio
async def test_uninstall_agent_endpoint_failure(client, db, monkeypatch):
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
    from sqlalchemy import select
    token_obj = (await db.execute(select(AgentToken).where(AgentToken.device_id == device.id))).scalar_one_or_none()
    assert token_obj is not None
