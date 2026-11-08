"""Helpers and error paths of app/api/ssh.py: profile validation, vault failures, one-shot
tickets, building a connection target from a profile or ad hoc, and the 404s of the key,
profile and known-host endpoints."""

import time

import pytest
from fastapi import HTTPException

import app.api.ssh as ssh_api
from app.models.device import Device
from app.models.ssh import SshKey, SshProfile
from app.schemas.ssh import SshSessionPrepare
from app.services.secret_vault import SecretVault, VaultError
from app.services.ssh_terminal import ConnectionTarget


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = SecretVault(key_file=tmp_path / "ssh_vault.key", env_key="")
    monkeypatch.setattr(ssh_api, "vault", v)
    return v


@pytest.fixture(autouse=True)
def clear_tickets():
    ssh_api._tickets.clear()
    yield
    ssh_api._tickets.clear()


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


async def _key(db, vault):
    key = SshKey(name="lab", key_type="ssh-ed25519", fingerprint="SHA256:abc", public_key="ssh-ed25519 AAAA",
                 encrypted_private_key=vault.encrypt("PEM"), encrypted_passphrase=vault.encrypt("secret"))
    db.add(key)
    await db.commit()
    return key


def _profile(**kw):
    base = dict(name="nas", username="admin", host="192.0.2.10", port=22, auth_method="password", encrypted_password="x")
    base.update(kw)
    return SshProfile(**base)


# --- profile validation -------------------------------------------------------------------------

@pytest.mark.parametrize("profile, message", [
    (_profile(name="  "), "Name is required."),
    (_profile(username=" "), "Username is required."),
    (_profile(host=None), "Choose a device or enter a host."),
    (_profile(device_id=9999), "Device not found."),
    (_profile(auth_method="key", key_id=None), "Choose a stored key"),
    (_profile(auth_method="key", key_id=9999), "Choose a stored key"),
    (_profile(encrypted_password=None), "Enter a password or choose 'ask every time'."),
])
async def test_profile_validation(db, profile, message):
    with pytest.raises(HTTPException) as exc:
        await ssh_api._validate_profile(db, profile)
    assert exc.value.status_code == 400 and message in exc.value.detail


async def test_an_ask_every_time_profile_is_valid(db):
    await ssh_api._validate_profile(db, _profile(auth_method="ask", encrypted_password=None))


# --- vault failures ----------------------------------------------------------------------------

def test_vault_failures_become_500(monkeypatch):
    class Broken:
        def encrypt(self, value):
            raise VaultError("no key")

        def decrypt_optional(self, value):
            raise VaultError("wrong key")

    monkeypatch.setattr(ssh_api, "vault", Broken())
    for call in (lambda: ssh_api._encrypt("x"), lambda: ssh_api._decrypt("x")):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 500


# --- tickets -----------------------------------------------------------------------------------

TARGET = ConnectionTarget(host="192.0.2.10", port=22, username="admin", label="nas")


def test_tickets_are_one_shot_and_expire():
    assert ssh_api.consume_ticket(None) is None
    assert ssh_api.consume_ticket("unknown") is None

    token = ssh_api._issue_ticket(TARGET)
    assert ssh_api.consume_ticket(token) is TARGET
    assert ssh_api.consume_ticket(token) is None

    old = ssh_api._issue_ticket(TARGET)
    ssh_api._tickets[old] = ssh_api._tickets[old]._replace(created=time.monotonic() - 3600)
    assert ssh_api.consume_ticket(old) is None


def test_expired_tickets_are_purged_when_a_new_one_is_issued():
    old = ssh_api._issue_ticket(TARGET)
    ssh_api._tickets[old] = ssh_api._tickets[old]._replace(created=time.monotonic() - 3600)
    ssh_api._issue_ticket(TARGET)
    assert old not in ssh_api._tickets


def test_session_bound_tickets_need_the_same_client():
    token = ssh_api._issue_ticket(TARGET, from_session=True, client="192.0.2.50")
    assert ssh_api.consume_ticket(token, require_session=True, client="192.0.2.99") is None
    token = ssh_api._issue_ticket(TARGET, from_session=False, client="192.0.2.50")
    assert ssh_api.consume_ticket(token, require_session=True, client="192.0.2.50") is None
    token = ssh_api._issue_ticket(TARGET, from_session=True, client="192.0.2.50")
    assert ssh_api.consume_ticket(token, require_session=True, client="192.0.2.50") is TARGET


# --- connection targets ------------------------------------------------------------------------

async def test_target_from_profile_variants(db, vault):
    key = await _key(db, vault)
    dev = Device(ip="192.0.2.20", display_name="NAS")
    db.add(dev)
    await db.commit()

    key_profile = _profile(host=None, device_id=dev.id, auth_method="key", key_id=key.id)
    by_key = await ssh_api._target_from_profile(db, key_profile, None)
    assert (by_key.host, by_key.private_key, by_key.passphrase) == ("192.0.2.20", "PEM", "secret")

    stored = await ssh_api._target_from_profile(db, _profile(encrypted_password=vault.encrypt("pw")), None)
    assert stored.password == "pw"
    typed = await ssh_api._target_from_profile(db, _profile(auth_method="ask", encrypted_password=None), "typed")
    assert typed.password == "typed"


@pytest.mark.parametrize("profile, password, message", [
    (_profile(host=None), None, "no reachable host"),
    (_profile(auth_method="key", key_id=None), None, "no SSH key assigned"),
    (_profile(auth_method="key", key_id=9999), None, "no longer exists"),
    (_profile(auth_method="ask", encrypted_password=None), None, "Password required."),
])
async def test_target_from_profile_errors(db, vault, profile, password, message):
    with pytest.raises(HTTPException) as exc:
        await ssh_api._target_from_profile(db, profile, password)
    assert exc.value.status_code == 400 and message in exc.value.detail


async def test_ad_hoc_target_variants(db, vault):
    key = await _key(db, vault)
    dev = Device(ip="192.0.2.20", display_name="NAS")
    db.add(dev)
    await db.commit()

    by_device = await ssh_api._target_ad_hoc(db, SshSessionPrepare(device_id=dev.id, username=" root ", key_id=key.id))
    assert (by_device.host, by_device.username, by_device.label, by_device.private_key) == ("192.0.2.20", "root", "root@NAS", "PEM")
    by_host = await ssh_api._target_ad_hoc(db, SshSessionPrepare(host="192.0.2.30", username="admin", password="pw"))
    assert (by_host.label, by_host.password) == ("admin@192.0.2.30", "pw")


@pytest.mark.parametrize("req, status, message", [
    (SshSessionPrepare(device_id=9999, username="admin", password="pw"), 404, "Device not found."),
    (SshSessionPrepare(username="admin", password="pw"), 400, "Choose a device or enter a host."),
    (SshSessionPrepare(host="192.0.2.30", username=" ", password="pw"), 400, "Username is required."),
    (SshSessionPrepare(host="192.0.2.30", username="admin"), 400, "Choose a key or enter a password."),
])
async def test_ad_hoc_target_errors(db, req, status, message):
    with pytest.raises(HTTPException) as exc:
        await ssh_api._target_ad_hoc(db, req)
    assert (exc.value.status_code, exc.value.detail) == (status, message)


# --- endpoint errors ---------------------------------------------------------------------------

async def test_unknown_keys_profiles_and_known_hosts(client, auth, vault):
    assert (await client.patch("/api/ssh/keys/9999", json={"name": "x"}, headers=auth)).status_code == 404
    assert (await client.delete("/api/ssh/keys/9999", headers=auth)).status_code == 404
    assert (await client.patch("/api/ssh/profiles/9999", json={"name": "x"}, headers=auth)).status_code == 404
    assert (await client.delete("/api/ssh/profiles/9999", headers=auth)).status_code == 404
    assert (await client.delete("/api/ssh/known-hosts/9999", headers=auth)).status_code == 404


async def test_key_rename_and_delete(client, auth, db, vault):
    key = await _key(db, vault)
    assert (await client.patch(f"/api/ssh/keys/{key.id}", json={"name": "  "}, headers=auth)).status_code == 400
    renamed = await client.patch(f"/api/ssh/keys/{key.id}", json={"name": " homelab "}, headers=auth)
    assert renamed.json()["name"] == "homelab"
    assert (await client.delete(f"/api/ssh/keys/{key.id}", headers=auth)).json() == {"status": "ok"}
