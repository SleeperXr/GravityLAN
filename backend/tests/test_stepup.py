"""Step-up (AP-12): a browser session confirms the password again before sensitive actions."""

import pytest
from sqlalchemy import select

from app.api.auth import LOGIN_MAX_FAILURES
from app.models.audit import AuditEvent
from app.models.device import Device
from app.models.setting import Setting
from app.services import stepup
from app.services.auth_service import hash_password
from app.services.session_service import session_store

MASTER = {"Authorization": "Bearer test-admin-token-12345"}
PASSWORD = "right-password"


@pytest.fixture(autouse=True)
def fresh_grants():
    stepup.store.clear()
    yield
    stepup.store.clear()


@pytest.fixture
async def browser(client, db, admin_token):
    """The client as a logged-in browser session; the admin password is PASSWORD."""
    db.add(Setting(key="api.admin_password", value=hash_password(PASSWORD)))
    await db.commit()
    session_id = session_store.create_session(user_agent=None)
    client.cookies.set("gravitylan_token", session_id)
    yield client
    client.cookies.clear()


@pytest.fixture
async def device(db, admin_token):
    dev = Device(ip="192.168.1.70", display_name="Pi", is_online=True)
    db.add(dev)
    await db.commit()
    await db.refresh(dev)
    return dev


async def _deploy(client, device, headers=None):
    return await client.post(
        f"/api/agent/deploy/{device.id}", json={"ssh_user": "root", "ssh_password": "x"}, headers=headers or {},
    )


@pytest.fixture
def no_ssh(monkeypatch):
    async def fake_deploy(**kwargs):
        return False, "no SSH in tests", ""
    monkeypatch.setattr("app.api.agent.deploy_agent", fake_deploy)


@pytest.mark.asyncio
async def test_a_session_without_confirmation_is_asked_for_it(browser, device, no_ssh):
    res = await _deploy(browser, device)
    assert res.status_code == 403
    assert res.headers["X-Step-Up"] == "remote"
    assert "GravityUI" in res.json()["detail"]  # readable for the classic view


@pytest.mark.asyncio
async def test_confirming_allows_that_class_only(browser, device, no_ssh, db):
    wrong = await browser.post("/api/auth/step-up", json={"password": "nope", "scope": "remote"})
    assert wrong.status_code == 400
    ok = await browser.post("/api/auth/step-up", json={"password": PASSWORD, "scope": "remote"})
    assert ok.status_code == 200 and ok.json()["expires_in"] == 600

    assert (await _deploy(browser, device)).json()["status"] == "failed"  # got past the step-up
    token = await browser.post("/api/auth/tokens", json={"name": "x"})
    assert token.status_code == 403 and token.headers["X-Step-Up"] == "credentials"

    status = (await browser.get("/api/auth/step-up")).json()
    assert set(status["grants"]) == {"remote"} and status["minutes"] == 10
    stepups = (await db.execute(select(AuditEvent).where(AuditEvent.action == "auth.stepup"))).scalars().all()
    assert [e.result for e in stepups] == ["failed", "ok"]


@pytest.mark.asyncio
async def test_tokens_are_not_asked(client, device, no_ssh, admin_token):
    """API and master tokens have no session; AP-13 decides what they may do."""
    assert (await _deploy(client, device, MASTER)).json()["status"] == "failed"
    res = await client.post("/api/auth/step-up", json={"password": PASSWORD, "scope": "remote"}, headers=MASTER)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_a_grant_runs_out(browser, device, no_ssh, monkeypatch):
    await browser.post("/api/auth/step-up", json={"password": PASSWORD, "scope": "remote"})
    now = stepup.time.monotonic()
    monkeypatch.setattr(stepup.time, "monotonic", lambda: now + 601)
    assert (await _deploy(browser, device)).status_code == 403


@pytest.mark.asyncio
async def test_wrong_passwords_share_the_login_limit(browser):
    for _ in range(LOGIN_MAX_FAILURES):
        assert (await browser.post("/api/auth/step-up", json={"password": "nope", "scope": "instance"})).status_code == 400
    blocked = await browser.post("/api/auth/step-up", json={"password": PASSWORD, "scope": "instance"})
    assert blocked.status_code == 429


@pytest.mark.asyncio
async def test_changing_the_grant_length_needs_a_confirmation(browser):
    # Saving the settings form unchanged must not ask
    assert (await browser.post("/api/settings", json={"security.stepup_minutes": "10"})).status_code == 200
    changed = await browser.post("/api/settings", json={"security.stepup_minutes": "30"})
    assert changed.status_code == 403 and changed.headers["X-Step-Up"] == "instance"

    await browser.post("/api/auth/step-up", json={"password": PASSWORD, "scope": "instance"})
    assert (await browser.post("/api/settings", json={"security.stepup_minutes": "30"})).status_code == 200
    assert (await browser.post("/api/settings", json={"security.stepup_minutes": "61"})).status_code == 400

    await browser.post("/api/auth/step-up", json={"password": PASSWORD, "scope": "remote"})
    assert set((await browser.get("/api/auth/step-up")).json()["grants"]) == {"instance", "remote"}
    assert (await browser.get("/api/auth/step-up")).json()["minutes"] == 30


@pytest.mark.asyncio
async def test_every_class_guards_its_endpoints(browser, device):
    calls = {
        "remote": [("post", f"/api/agent/uninstall/{device.id}", {"ssh_user": "root"}), ("post", "/api/ssh/sessions/prepare", {"host": "10.0.0.1", "username": "root"}),
                   ("post", f"/api/agent/patches/{device.id}/prepare", {"mode": "all"})],
        "credentials": [("post", "/api/ssh/keys/generate", {"name": "k"}), ("delete", "/api/ssh/known-hosts/1", None),
                        ("post", "/api/webhooks", {"url": "https://hook.example/x", "events": ["device.offline"]})],
        "instance": [("get", "/api/backup/export", None), ("post", "/api/settings/reset-db", None)],
    }
    for cls, requests in calls.items():
        for method, path, body in requests:
            res = await getattr(browser, method)(path, **({"json": body} if body is not None else {}))
            assert (res.status_code, res.headers.get("X-Step-Up")) == (403, cls), path
