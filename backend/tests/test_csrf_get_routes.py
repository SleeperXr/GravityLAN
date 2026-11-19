"""GET routes with side effects take no session cookie; browsers use POST (CSRF, SameSite=Lax)."""

import hashlib
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.api import scanner
from app.models.agent import AgentToken
from app.models.api_token import ApiToken
from app.models.audit import AuditEvent
from app.models.device import Device
from app.models.setting import Setting
from app.services.session_service import session_store

MASTER = {"Authorization": "Bearer test-admin-token-12345"}


@pytest.fixture
async def device(db, admin_token, monkeypatch):
    dev = Device(ip="192.168.1.50", display_name="Pi", is_online=True)
    db.add(dev)
    db.add(Setting(key="server.url", value="http://gravity.example:9000"))
    await db.commit()
    await db.refresh(dev)
    monkeypatch.setattr("app.scanner.utils.get_local_subnets", None)
    return dev


def _login(client):
    client.cookies.set("gravitylan_token", session_store.create_session(user_agent=None))


async def _audit_actions(db, action):
    return (await db.execute(select(AuditEvent).where(AuditEvent.action == action))).scalars().all()


# --- agent config -------------------------------------------------------------

@pytest.mark.asyncio
async def test_config_get_with_a_session_cookie_is_refused_and_keeps_the_agent_token(client, db, device):
    """A link on another site must not rotate the token of a running agent."""
    db.add(AgentToken(device_id=device.id, token="running-agent", is_active=True))
    await db.commit()
    _login(client)

    response = await client.get(f"/api/agent/download/config/{device.id}")

    assert response.status_code == 403
    assert "POST" in response.json()["detail"]
    token = (await db.execute(select(AgentToken).where(AgentToken.device_id == device.id))).scalar_one()
    assert token.token == "running-agent"


@pytest.mark.asyncio
async def test_config_post_for_a_browser_session_is_audited(client, db, device):
    _login(client)

    response = await client.post(f"/api/agent/download/config/{device.id}")

    assert response.status_code == 200
    assert json.loads(response.text)["device_id"] == device.id
    events = await _audit_actions(db, "agent.config_download")
    assert [(e.device_id, e.result) for e in events] == [(device.id, "ok")]


@pytest.mark.asyncio
async def test_config_post_refuses_the_master_token(client, db, device):
    """POST is the browser route with password confirmation; scripts keep using GET with the token."""
    response = await client.post(f"/api/agent/download/config/{device.id}", headers=MASTER)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_config_get_with_the_master_token_is_audited(client, db, device):
    response = await client.get(f"/api/agent/download/config/{device.id}", headers=MASTER)

    assert response.status_code == 200
    events = await _audit_actions(db, "agent.config_download")
    assert [(e.device_id, e.detail, e.actor) for e in events] == [(device.id, "master token", "master")]


@pytest.mark.asyncio
async def test_config_get_checks_the_bearer_token_even_with_a_valid_cookie(client, db, device):
    """The cookie used to be checked first, so any Bearer value passed next to a session."""
    _login(client)
    response = await client.get(
        f"/api/agent/download/config/{device.id}", headers={"Authorization": "Bearer not-the-master-token"}
    )
    assert response.status_code in (401, 403)
    assert (await db.execute(select(AgentToken).where(AgentToken.device_id == device.id))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_config_download_with_an_install_code_is_audited(client, db, device):
    from app.services.enrollment_service import enrollment_store

    code = enrollment_store.issue(device.id)
    response = await client.get(f"/api/agent/download/config/{device.id}", params={"code": code})
    assert response.status_code == 200
    bad = await client.get(f"/api/agent/download/config/{device.id}", params={"code": code})
    assert bad.status_code == 403

    events = await _audit_actions(db, "agent.config_download")
    assert [(e.device_id, e.detail, e.actor) for e in events] == [(device.id, "install code", "install script")]
    assert code not in str([(e.detail, e.target) for e in events])


# --- scanner ------------------------------------------------------------------

@pytest.fixture
def no_nmap(monkeypatch, db):
    @asynccontextmanager
    async def test_session():
        yield db

    monkeypatch.setattr(scanner, "async_session", test_session)
    monkeypatch.setattr(scanner, "nmap_scan", AsyncMock(return_value=[{"port": 22}]))
    monkeypatch.setattr(scanner, "scan_ports", AsyncMock(return_value=[]))
    discover = AsyncMock(return_value=[{"ip": "192.168.1.9"}])
    monkeypatch.setattr(scanner, "_discover_and_sync_subnet", discover)
    return discover


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["/api/scanner/scan-ip?ip=192.168.1.10", "/api/scanner/live-discovery?subnets=192.168.1.0/24"])
async def test_scanner_gets_refuse_a_session_cookie(client, admin_token, no_nmap, url):
    _login(client)
    response = await client.get(url)
    assert response.status_code == 403
    no_nmap.assert_not_awaited()


@pytest.mark.asyncio
async def test_scanner_gets_still_take_a_bearer_token(client, admin_token, no_nmap):
    response = await client.get("/api/scanner/scan-ip", params={"ip": "192.168.1.10"}, headers=MASTER)
    assert response.status_code == 200
    assert response.json()["ports"] == [{"port": 22}]


@pytest.mark.asyncio
async def test_scanner_posts_work_for_a_browser_session(client, admin_token, no_nmap):
    _login(client)

    scan = await client.post("/api/scanner/scan-ip", json={"ip": "192.168.1.10"})
    assert scan.status_code == 200 and scan.json()["ip"] == "192.168.1.10"

    live = await client.post("/api/scanner/live-discovery", json={"subnets": ["192.168.1.0/24"]})
    assert live.status_code == 200 and live.json() == [{"ip": "192.168.1.9"}]
    assert no_nmap.await_args.args[1] == "192.168.1.0/24"


@pytest.mark.asyncio
async def test_scan_ip_post_validates_the_address(client, admin_token, no_nmap):
    _login(client)
    response = await client.post("/api/scanner/scan-ip", json={"ip": "300.1.1.1"})
    assert response.status_code == 400


# --- backup import ------------------------------------------------------------

@pytest.mark.asyncio
async def test_backup_import_is_refused_to_api_tokens_even_with_backup_write(client, db, admin_token):
    """Import overwrites the database; scoped tokens cannot reach it, like export and reset-db."""
    raw = "gl_pat_backupwriter"
    db.add(ApiToken(name="backup", token_hash=hashlib.sha256(raw.encode()).hexdigest(), prefix="gl_pat",
                    scopes="backup:read,backup:write", is_active=True))
    await db.commit()

    response = await client.post(
        "/api/backup/import",
        files={"file": ("backup.json", b"{}", "application/json")},
        headers={"Authorization": f"Bearer {raw}"},
    )

    assert response.status_code == 403
