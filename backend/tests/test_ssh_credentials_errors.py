"""Failures of stored SSH logins (app/services/ssh_credentials.py): missing keys and an undecryptable vault."""

import pytest

import app.services.ssh_credentials as ssh_credentials
from app.models.device import Device
from app.models.ssh import SshKey, SshKnownHost, SshProfile
from app.services.secret_vault import SecretVault, VaultError
from app.services.ssh_credentials import StoredLoginError, resolve_key_profile, resolve_stored_key


@pytest.fixture
def test_vault(tmp_path, monkeypatch):
    vault = SecretVault(key_file=tmp_path / "ssh_vault.key", env_key="")
    monkeypatch.setattr(ssh_credentials, "vault", vault)
    return vault


async def _seed(db, vault, *, with_key=True):
    device = Device(ip="192.0.2.60", display_name="Pi")
    db.add(device)
    await db.flush()
    key = SshKey(name="Homelab", key_type="ssh-ed25519", fingerprint="SHA256:userkey", public_key="ssh-ed25519 AAAA",
                 encrypted_private_key=vault.encrypt("PRIVATE"), encrypted_passphrase=vault.encrypt("phrase"))
    db.add(key)
    await db.flush()
    profile = SshProfile(name="Pi admin", device_id=device.id, port=22, username="pi", auth_method="key", key_id=key.id)
    db.add_all([profile, SshKnownHost(host=device.ip, port=22, key_type="ssh-ed25519", fingerprint="SHA256:host",
                                      public_key="ssh-ed25519 AAAA")])
    await db.commit()
    if not with_key:
        await db.delete(key)
        await db.commit()
    return device, profile, key


def _broken_vault(monkeypatch):
    def fail(_value):
        raise VaultError("wrong vault key")

    monkeypatch.setattr(ssh_credentials.vault, "decrypt", fail)


@pytest.mark.asyncio
async def test_a_profile_whose_key_is_gone(db, test_vault):
    device, profile, _ = await _seed(db, test_vault, with_key=False)
    with pytest.raises(StoredLoginError, match="SSH key of this saved connection no longer exists") as err:
        await resolve_key_profile(db, profile.id, device)
    assert err.value.status_code == 400


@pytest.mark.asyncio
async def test_a_profile_whose_key_cannot_be_decrypted(db, test_vault, monkeypatch):
    device, profile, _ = await _seed(db, test_vault)
    _broken_vault(monkeypatch)
    with pytest.raises(StoredLoginError, match="could not be decrypted") as err:
        await resolve_key_profile(db, profile.id, device)
    assert err.value.status_code == 500


@pytest.mark.asyncio
async def test_a_stored_key_by_id(db, test_vault, monkeypatch):
    _, _, key = await _seed(db, test_vault)
    assert await resolve_stored_key(db, key.id) == ("PRIVATE", "phrase")
    # A passphrase typed by the user wins over the stored one
    assert await resolve_stored_key(db, key.id, "typed") == ("PRIVATE", "typed")
    assert key.last_used_at is not None

    with pytest.raises(StoredLoginError, match="no longer exists") as err:
        await resolve_stored_key(db, key.id + 999)
    assert err.value.status_code == 404

    _broken_vault(monkeypatch)
    with pytest.raises(StoredLoginError, match="could not be decrypted") as err:
        await resolve_stored_key(db, key.id)
    assert err.value.status_code == 500
