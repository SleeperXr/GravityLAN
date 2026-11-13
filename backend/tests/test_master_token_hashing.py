"""The master token is stored only as a tagged SHA-256: a copied database must not hand out admin access."""
import hashlib

import pytest
from sqlalchemy import select

from app.models.setting import Setting

TOKEN = "a-master-token-the-client-knows"
STORED = "sha256:" + hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()


def _bearer(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


async def _instance(db, master_value: str, with_password: bool = True) -> None:
    db.add(Setting(key="setup.complete", value="true"))
    db.add(Setting(key="api.master_token", value=master_value))
    if with_password:
        from app.services.auth_service import hash_password
        db.add(Setting(key="api.admin_password", value=hash_password("an-admin-password")))
    await db.commit()


async def _stored_master(db) -> str:
    row = (await db.execute(select(Setting).where(Setting.key == "api.master_token"))).scalar_one()
    await db.refresh(row)
    return row.value


@pytest.mark.asyncio
async def test_hashed_master_token_still_authenticates(client, db):
    await _instance(db, STORED)
    assert (await client.get("/api/settings", headers=_bearer(TOKEN))).status_code == 200


@pytest.mark.asyncio
async def test_stored_hash_is_not_accepted_as_the_token(client, db):
    # Whoever copies the database only sees STORED; it must not work as a token
    await _instance(db, STORED)
    assert (await client.get("/api/settings", headers=_bearer(STORED))).status_code == 401


@pytest.mark.asyncio
async def test_setup_stores_only_the_hash(client, db):
    res = await client.post("/api/setup/complete", json={"admin_password": "supersecretpassword123"})
    assert res.status_code == 200
    stored = await _stored_master(db)
    assert stored.startswith("sha256:")
    assert len(stored) == len("sha256:") + 64


@pytest.mark.asyncio
async def test_login_falls_back_to_the_hashed_master_token_without_a_password(client, db):
    await _instance(db, STORED, with_password=False)
    assert (await client.post("/api/auth/login", json={"password": TOKEN})).status_code == 200
    assert (await client.post("/api/auth/login", json={"password": STORED})).status_code == 401


@pytest.mark.asyncio
async def test_migration_hashes_a_plaintext_token_once(client, db):
    from app.database.migrations import _hash_master_token

    await _instance(db, TOKEN)
    await _hash_master_token(db)
    assert await _stored_master(db) == STORED
    await _hash_master_token(db)  # a second start leaves the hash alone
    assert await _stored_master(db) == STORED
    assert (await client.get("/api/settings", headers=_bearer(TOKEN))).status_code == 200


@pytest.mark.asyncio
async def test_plaintext_token_still_works_until_the_migration_ran(client, db):
    await _instance(db, TOKEN)
    assert (await client.get("/api/settings", headers=_bearer(TOKEN))).status_code == 200
