"""Audit log (AP-11): who did what, never a secret."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.device import Device
from app.services import audit as audit_service

MASTER = "test-admin-token-12345"
HEADERS = {"Authorization": f"Bearer {MASTER}"}
LOGIN = {"ssh_user": "root", "ssh_password": "secret-ssh-pw", "sudo_password": "secret-sudo-pw"}


async def _events(db, action_prefix: str = "") -> list[AuditEvent]:
    rows = (await db.execute(select(AuditEvent).order_by(AuditEvent.id))).scalars().all()
    return [r for r in rows if r.action.startswith(action_prefix)]


def _text(rows) -> str:
    return " ".join(f"{r.actor} {r.action} {r.target} {r.detail}" for r in rows)


def test_actor_never_keeps_a_token_value():
    assert audit_service.actor_from_identity("session_abc") == "session"
    assert audit_service.actor_from_identity("api_token:homeassistant") == "api_token:homeassistant"
    assert audit_service.actor_from_identity(MASTER) == "master"
    assert audit_service.actor_from_identity(None) == "anonymous"


@pytest.mark.asyncio
async def test_failed_and_successful_logins_are_recorded(client, db, admin_token):
    from app.models.setting import Setting
    from app.services.auth_service import hash_password
    db.add(Setting(key="api.admin_password", value=hash_password("right-password")))
    await db.commit()

    assert (await client.post("/api/auth/login", json={"password": "wrong-password"})).status_code == 401
    assert (await client.post("/api/auth/login", json={"password": "right-password"})).status_code == 200

    rows = await _events(db, "auth.login")
    assert [(r.result, r.actor) for r in rows] == [("failed", "anonymous"), ("ok", "session")]
    assert "right-password" not in _text(rows) and "wrong-password" not in _text(rows)


@pytest.mark.asyncio
async def test_token_management_names_the_master_but_not_its_value(client, db, admin_token):
    created = await client.post("/api/auth/tokens", json={"name": "homeassistant"}, headers=HEADERS)
    assert created.status_code == 200
    token_value = created.json()["token"]
    await client.delete(f"/api/auth/tokens/{created.json()['id']}", headers=HEADERS)

    rows = await _events(db, "auth.token")
    assert [(r.action, r.actor, r.target) for r in rows] == [
        ("auth.token.create", "master", "homeassistant"),
        ("auth.token.delete", "master", "homeassistant"),
    ]
    assert MASTER not in _text(rows) and token_value not in _text(rows)


@pytest.fixture
async def device(db, admin_token):
    dev = Device(ip="192.168.1.70", display_name="Pi", is_online=True)
    db.add(dev)
    await db.commit()
    await db.refresh(dev)
    return dev


@pytest.mark.asyncio
async def test_failed_deploy_is_recorded_without_credentials(client, db, device, monkeypatch):
    async def fake_deploy(**kwargs):
        return False, "SSH authentication failed", ""
    monkeypatch.setattr("app.api.agent.deploy_agent", fake_deploy)

    res = await client.post(f"/api/agent/deploy/{device.id}", json=LOGIN, headers=HEADERS)
    assert res.json()["status"] == "failed"

    (row,) = await _events(db, "agent.deploy")
    assert (row.result, row.device_id, row.target, row.actor) == ("failed", device.id, "Pi (192.168.1.70)", "master")
    assert "secret" not in _text([row])


@pytest.mark.asyncio
async def test_webhook_keeps_only_the_host_of_its_url(client, db, admin_token):
    url = "https://ntfy.example.com/gravitylan?auth=topsecret"
    res = await client.post("/api/webhooks", json={"url": url, "events": ["device.offline"]}, headers=HEADERS)
    assert res.status_code == 200

    (row,) = await _events(db, "webhook")
    assert row.target == "ntfy.example.com"
    assert "topsecret" not in _text([row])


@pytest.mark.asyncio
async def test_audit_api_filters_and_pages(client, db, admin_token):
    for i in range(5):
        db.add(AuditEvent(actor="session", action="ssh.terminal.open", result="ok", target=f"root@host{i}:22"))
    db.add(AuditEvent(actor="anonymous", action="auth.login", result="failed"))
    await db.commit()

    page = (await client.get("/api/audit", params={"action": "ssh", "limit": 3}, headers=HEADERS)).json()
    assert [e["target"] for e in page["items"]] == ["root@host4:22", "root@host3:22", "root@host2:22"]
    assert page["has_more"] is True and page["retention_days"] == 90
    assert page["items"][0]["created_at"].endswith(("Z", "+00:00"))

    rest = (await client.get("/api/audit", params={"action": "ssh", "before_id": page["items"][-1]["id"]}, headers=HEADERS)).json()
    assert [e["target"] for e in rest["items"]] == ["root@host1:22", "root@host0:22"] and rest["has_more"] is False

    failed = (await client.get("/api/audit", params={"result": "failed"}, headers=HEADERS)).json()["items"]
    assert [e["action"] for e in failed] == ["auth.login"]

    both = (await client.get("/api/audit", params={"action": "auth.login,ssh.terminal", "limit": 2}, headers=HEADERS)).json()
    assert [e["action"] for e in both["items"]] == ["auth.login", "ssh.terminal.open"]
    # A prefix matches whole name parts only: "ssh.term" is not "ssh.terminal"
    assert (await client.get("/api/audit", params={"action": "ssh.term"}, headers=HEADERS)).json()["items"] == []


@pytest.mark.asyncio
async def test_prune_drops_entries_older_than_90_days(db):
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=91)
    db.add(AuditEvent(actor="session", action="backup.export", created_at=old))
    db.add(AuditEvent(actor="session", action="backup.export"))
    await db.commit()

    assert await audit_service.prune(db) == 1
    assert len(await _events(db)) == 1


@pytest.mark.asyncio
async def test_reset_keeps_the_audit_log_and_records_itself(db, monkeypatch):
    from app.api.settings import reset_database
    from app.scanner.scheduler import scheduler

    async def noop():
        return None
    monkeypatch.setattr(scheduler, "stop", noop)
    monkeypatch.setattr(scheduler, "start", noop)
    db.add(AuditEvent(actor="session", action="agent.deploy", result="ok"))
    await db.commit()

    await reset_database(request=None, db=db)

    assert [r.action for r in await _events(db)] == ["agent.deploy", "database.reset"]


@pytest.mark.asyncio
async def test_a_broken_audit_write_never_breaks_the_action(client, db, admin_token, monkeypatch):
    def broken_session():
        raise RuntimeError("disk full")
    monkeypatch.setattr("app.services.audit.async_session", broken_session)

    res = await client.post("/api/auth/tokens", json={"name": "still-works"}, headers=HEADERS)
    assert res.status_code == 200
