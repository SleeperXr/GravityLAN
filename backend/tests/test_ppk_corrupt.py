"""Damaged and unusual PuTTY key files (app/services/ppk.py), built here so every check can be hit on its own.

``_ppk`` writes an unencrypted format-3 file (MAC key empty, HMAC-SHA-256), so a file passes the MAC
check and fails only where the test wants it to.
"""

import base64
import hashlib
import hmac
import struct

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from app.services.ppk import PpkError, PpkPassphraseRequired, ppk_to_openssh


def _s(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


def _mpint(value: int) -> bytes:
    return _s(value.to_bytes((value.bit_length() + 8) // 8 or 1, "big", signed=True))


def _ppk(algorithm: str, public: bytes, private: bytes, *, encryption="none", extra="", version=3) -> str:
    comment = "test"
    mac_data = b"".join(_s(p) for p in (algorithm.encode(), encryption.encode(), comment.encode(), public, private))
    digest = hmac.new(b"", mac_data, hashlib.sha256).hexdigest()
    pub64, priv64 = base64.b64encode(public).decode(), base64.b64encode(private).decode()
    return (
        f"PuTTY-User-Key-File-{version}: {algorithm}\nEncryption: {encryption}\nComment: {comment}\n"
        f"Public-Lines: 1\n{pub64}\n{extra}Private-Lines: 1\n{priv64}\nPrivate-MAC: {digest}\n"
    )


def _ed25519():
    key = ed25519.Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return _s(b"ssh-ed25519") + _s(public), seed


def test_a_self_built_ed25519_key_converts():
    public, seed = _ed25519()
    assert ppk_to_openssh(_ppk("ssh-ed25519", public, _s(seed))).startswith("-----BEGIN OPENSSH PRIVATE KEY-----")


def test_header_lines_without_a_colon_are_ignored():
    public, seed = _ed25519()
    text = _ppk("ssh-ed25519", public, _s(seed)).replace("Comment: test\n", "Comment: test\nstray line\n")
    assert ppk_to_openssh(text).startswith("-----BEGIN OPENSSH")


def test_broken_base64():
    public, seed = _ed25519()
    text = _ppk("ssh-ed25519", public, _s(seed)).replace("Private-Lines: 1\n", "Private-Lines: 1\n!!!")
    with pytest.raises(PpkError, match="base64"):
        ppk_to_openssh(text)


def test_unsupported_encryption():
    public, seed = _ed25519()
    with pytest.raises(PpkError, match="unsupported encryption 'aes128-ctr'"):
        ppk_to_openssh(_ppk("ssh-ed25519", public, _s(seed), encryption="aes128-ctr"))


def test_encrypted_private_data_of_a_wrong_length():
    public, _ = _ed25519()
    with pytest.raises(PpkError, match="private data length"):
        ppk_to_openssh(_ppk("ssh-ed25519", public, b"12345", encryption="aes256-cbc", version=2), "pass")


def test_encrypted_v3_without_a_passphrase_asks_for_one():
    public, _ = _ed25519()
    with pytest.raises(PpkPassphraseRequired):
        ppk_to_openssh(_ppk("ssh-ed25519", public, b"0" * 16, encryption="aes256-cbc"))


@pytest.mark.parametrize("extra, message", [
    ("Key-Derivation: scrypt\n", "unsupported key derivation 'scrypt'"),
    ("Key-Derivation: Argon2id\nArgon2-Memory: 8\n", "key derivation parameters"),  # salt and passes missing
    ("Key-Derivation: Argon2id\nArgon2-Memory: 8\nArgon2-Passes: x\nArgon2-Parallelism: 1\nArgon2-Salt: 00\n",
     "key derivation parameters"),
])
def test_bad_v3_key_derivation(extra, message):
    public, _ = _ed25519()
    with pytest.raises(PpkError, match=message):
        ppk_to_openssh(_ppk("ssh-ed25519", public, b"0" * 16, encryption="aes256-cbc", extra=extra), "pass")


@pytest.mark.parametrize("public", [
    b"\x00\x00",                                    # length field cut short
    _s(b"ssh-ed25519")[:4] + b"ssh",                # announces 11 bytes, 3 there
])
def test_truncated_blobs(public):
    with pytest.raises(PpkError, match="truncated"):
        ppk_to_openssh(_ppk("ssh-ed25519", public, b""))


def test_algorithm_in_the_blob_must_match_the_header():
    public, seed = _ed25519()
    with pytest.raises(PpkError, match="algorithm mismatch"):
        ppk_to_openssh(_ppk("ssh-rsa", public, _s(seed)))


def test_ed25519_private_half_must_match_the_public_half():
    public, _ = _ed25519()
    _, other_seed = _ed25519()
    with pytest.raises(PpkError, match="Ed25519 key does not match"):
        ppk_to_openssh(_ppk("ssh-ed25519", public, _s(other_seed)))


def test_rsa_parameters_must_fit_together():
    numbers = rsa.generate_private_key(public_exponent=65537, key_size=1024).private_numbers()
    public = _s(b"ssh-rsa") + _mpint(numbers.public_numbers.e) + _mpint(numbers.public_numbers.n)
    private = _mpint(numbers.d) + _mpint(numbers.p) + _mpint(numbers.q + 2) + _mpint(numbers.iqmp)
    with pytest.raises(PpkError, match="RSA parameters"):
        ppk_to_openssh(_ppk("ssh-rsa", public, private))


def _ecdsa_public(key, curve=b"nistp256"):
    point = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _s(b"ecdsa-sha2-" + curve) + _s(curve) + _s(point)


def test_ecdsa_unknown_curve_and_mismatching_halves():
    key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(PpkError, match="Unsupported ECDSA curve 'brainpool'"):
        ppk_to_openssh(_ppk("ecdsa-sha2-brainpool", _ecdsa_public(key, b"brainpool"), _mpint(1)))

    other = ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value
    with pytest.raises(PpkError, match="ECDSA key does not match"):
        ppk_to_openssh(_ppk("ecdsa-sha2-nistp256", _ecdsa_public(key), _mpint(other)))


def test_unsupported_key_type():
    with pytest.raises(PpkError, match="Unsupported PuTTY key type 'ssh-dss'"):
        ppk_to_openssh(_ppk("ssh-dss", _s(b"ssh-dss"), b""))
