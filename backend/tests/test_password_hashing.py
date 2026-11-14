"""Admin password hashing with argon2-cffi; hashes written by the passlib versions keep working."""
import pytest

from app.models.setting import Setting
from app.services.auth_service import hash_password, verify_password

# Written by GravityLAN 0.7.x (passlib 1.7.4, argon2 scheme) for the synthetic password below
LEGACY_PASSWORD = "legacy-synthetic-password"
LEGACY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$RkjpPSdkDMH43/t/TwnhHA$UEo2UjpsOdaFSwdcLykL7ObuF5pcCcaqXSAXpi+IfxU"


def test_a_hash_from_the_passlib_versions_still_verifies():
    assert verify_password(LEGACY_PASSWORD, LEGACY_HASH)
    assert not verify_password("wrong-password", LEGACY_HASH)


def test_new_hashes_are_argon2id_with_the_same_parameters():
    hashed = hash_password("a-new-password")
    assert hashed.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert verify_password("a-new-password", hashed)
    assert not verify_password("another-password", hashed)


@pytest.mark.parametrize("stored", ["$2b$12$" + "a" * 53, "$argon2id$broken", "not-a-hash"])
def test_anything_but_a_valid_argon2_hash_is_no_match(stored):
    assert verify_password("whatever", stored) is False


@pytest.mark.asyncio
async def test_login_with_a_hash_from_the_passlib_versions(client, db):
    db.add(Setting(key="setup.complete", value="true"))
    db.add(Setting(key="api.master_token", value="sha256:" + "0" * 64))
    db.add(Setting(key="api.admin_password", value=LEGACY_HASH))
    await db.commit()
    assert (await client.post("/api/auth/login", json={"password": LEGACY_PASSWORD})).status_code == 200
    assert (await client.post("/api/auth/login", json={"password": "wrong-password"})).status_code == 401
