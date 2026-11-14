"""The master token can be replaced from a confirmed browser session; the old one stops working at once."""
import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.setting import Setting
from app.services import stepup
from app.services.auth_service import hash_master_token, hash_password

PASSWORD = "an-admin-password"
OLD_TOKEN = "the-old-master-token"
ROTATE = "/api/auth/master-token/rotate"


def _bearer(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


@pytest.fixture(autouse=True)
def no_grants(_step_up_granted, monkeypatch):
    """conftest treats every session as confirmed; this module checks the real rule."""
    monkeypatch.setattr(stepup.store, "is_granted", stepup.StepUpStore.is_granted.__get__(stepup.store))
    stepup.store.clear()
    yield
    stepup.store.clear()


async def _instance(db) -> None:
    db.add(Setting(key="setup.complete", value="true"))
    db.add(Setting(key="api.master_token", value=hash_master_token(OLD_TOKEN)))
    db.add(Setting(key="api.admin_password", value=hash_password(PASSWORD)))
    await db.commit()


async def _confirmed_browser(client) -> None:
    assert (await client.post("/api/auth/login", json={"password": PASSWORD})).status_code == 200
    assert (await client.post("/api/auth/step-up", json={"password": PASSWORD, "scope": "credentials"})).status_code == 200


async def _stored(db) -> str:
    row = (await db.execute(select(Setting).where(Setting.key == "api.master_token"))).scalar_one()
    await db.refresh(row)
    return row.value


@pytest.mark.asyncio
async def test_a_session_has_to_confirm_first(client, db):
    await _instance(db)
    await client.post("/api/auth/login", json={"password": PASSWORD})
    res = await client.post(ROTATE)
    assert res.status_code == 403
    assert res.headers.get("X-Step-Up") == "credentials"
    assert await _stored(db) == hash_master_token(OLD_TOKEN)


@pytest.mark.asyncio
async def test_rotation_returns_a_new_token_once_and_stores_only_its_hash(client, db):
    await _instance(db)
    await _confirmed_browser(client)
    res = await client.post(ROTATE)
    assert res.status_code == 200
    new_token = res.json()["token"]
    assert len(new_token) == 64 and new_token != OLD_TOKEN
    assert await _stored(db) == hash_master_token(new_token)

    client.cookies.clear()
    assert (await client.get("/api/settings", headers=_bearer(OLD_TOKEN))).status_code == 401
    assert (await client.get("/api/settings", headers=_bearer(new_token))).status_code == 200


@pytest.mark.asyncio
async def test_the_master_token_cannot_replace_itself(client, db):
    await _instance(db)
    res = await client.post(ROTATE, headers=_bearer(OLD_TOKEN))
    assert res.status_code == 403
    assert await _stored(db) == hash_master_token(OLD_TOKEN)


@pytest.mark.asyncio
async def test_rotation_is_audited(client, db):
    await _instance(db)
    await _confirmed_browser(client)
    await client.post(ROTATE)
    actions = (await db.execute(select(AuditEvent.action, AuditEvent.result))).all()
    assert ("auth.master_token.rotate", "ok") in [tuple(a) for a in actions]
