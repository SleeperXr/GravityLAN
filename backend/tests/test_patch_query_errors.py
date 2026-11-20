"""A failed package query answers 400/409/502, never 500 (a 401 would sign GravityUI out)."""

import socket

import paramiko
import pytest

from app.models.device import Device
from app.services import patch_service
from app.services.session_service import session_store
from app.services.ssh_utils import HostKeyNotTrusted, SSHKeyPassphraseRequired


@pytest.mark.parametrize("exc, kind", [
    (paramiko.AuthenticationException("Authentication failed."), "login"),
    (paramiko.BadAuthenticationType("bad type", ["publickey"]), "login"),
    (HostKeyNotTrusted("Host key ssh-ed25519 SHA256:x of 192.0.2.1 is not the confirmed one"), "host_key"),
    (SSHKeyPassphraseRequired("The private key is encrypted: passphrase missing or wrong."), "credentials"),
    (ValueError("Invalid or unsupported private key format."), "credentials"),
    (socket.timeout("timed out"), "unreachable"),
    (ConnectionRefusedError("refused"), "unreachable"),
    (paramiko.SSHException("Error reading SSH protocol banner"), "unreachable"),
])
def test_ssh_failures_are_sorted_by_kind(exc, kind):
    assert patch_service.ssh_error_kind(exc) == kind


@pytest.mark.asyncio
@pytest.mark.parametrize("kind, status", [
    ("credentials", 400),
    ("login", 400),
    ("sudo", 400),
    ("host_key", 409),
    ("unreachable", 502),
    ("remote", 502),
    (None, 502),  # a result without a kind is still the host's failure
])
async def test_a_failed_query_answers_by_kind(client, db, admin_token, monkeypatch, kind, status):
    db.add(Device(id=77, ip="192.0.2.77", display_name="Host 77", is_online=True))
    await db.commit()

    async def failed_query(**kwargs):
        result = {"patch_manager": None, "packages": [], "error": "something went wrong on the host"}
        if kind:
            result["error_kind"] = kind
        return result

    monkeypatch.setattr("app.api.agent.list_device_updates", failed_query)
    client.cookies.set("gravitylan_token", session_store.create_session(user_agent=None))

    res = await client.post("/api/agent/patches/77/query", json={"ssh_user": "root", "ssh_password": "pw"})

    assert res.status_code == status
    assert res.json()["detail"] == "something went wrong on the host"
