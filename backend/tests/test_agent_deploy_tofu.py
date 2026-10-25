"""Agent deploy/uninstall with typed-in credentials: trust on first use, then pinned (#45)."""
from unittest.mock import patch

import paramiko
import pytest
from sqlalchemy import select

from app.config import settings
from app.models.device import Device
from app.models.ssh import SshKnownHost
from app.services import agent_deployer
from app.services.ssh_utils import HostKeyNotTrusted, PinnedHostKey, PinnedHostKeyPolicy, TofuHostKeyPolicy

HEADERS = {"Authorization": "Bearer test-admin-token-12345"}
LOGIN = {"ssh_user": "root", "ssh_password": "secret", "sudo_password": "sudo-secret"}


class _FakeKey:
    def __init__(self, fingerprint: str):
        self.fingerprint = fingerprint

    def get_name(self):
        return "ssh-ed25519"

    def get_base64(self):
        return "AAAAC3NzaC1lZDI1NTE5AAAAIFakeKey"


@pytest.fixture
async def device(db, admin_token):
    dev = Device(ip="192.168.1.70", display_name="Pi", is_online=True)
    db.add(dev)
    await db.commit()
    await db.refresh(dev)
    return dev


@pytest.fixture
def ssh_calls(monkeypatch):
    """Fake SSH boundary: the host presents a key through whichever policy the endpoint passed."""
    calls = []
    presented = {"key": _FakeKey("SHA256:first")}

    def _handshake(kwargs):
        calls.append(kwargs)
        pinned, tofu = kwargs.get("pinned_host_key"), kwargs.get("tofu_policy")
        policy = PinnedHostKeyPolicy(pinned) if pinned else tofu
        if policy is None:
            return False, "SSH connection rejected: Unknown host key."  # strict mode: RejectPolicy
        try:
            policy.missing_host_key(None, kwargs["host_ip"], presented["key"])
        except HostKeyNotTrusted as exc:
            return agent_deployer._map_ssh_error(exc, kwargs["host_ip"])
        return True, "ok"

    async def fake_deploy(**kwargs):
        ok, message = _handshake(kwargs)
        return ok, message, "token" if ok else ""

    async def fake_remove(**kwargs):
        return _handshake(kwargs)

    monkeypatch.setattr("app.api.agent.deploy_agent", fake_deploy)
    monkeypatch.setattr("app.api.agent.remove_agent", fake_remove)
    return calls, presented


async def _known_hosts(db):
    return (await db.execute(select(SshKnownHost))).scalars().all()


@pytest.mark.asyncio
async def test_first_deploy_stores_key_then_pins_it(client, db, device, ssh_calls):
    calls, _ = ssh_calls

    res = await client.post(f"/api/agent/deploy/{device.id}", json=LOGIN, headers=HEADERS)
    assert res.json()["status"] == "success"
    assert isinstance(calls[0]["tofu_policy"], TofuHostKeyPolicy)
    assert calls[0]["pinned_host_key"] is None

    stored = await _known_hosts(db)
    assert [(k.host, k.port, k.fingerprint) for k in stored] == [("192.168.1.70", 22, "SHA256:first")]

    res = await client.post(f"/api/agent/uninstall/{device.id}", json=LOGIN, headers=HEADERS)
    assert res.json()["status"] == "success"
    assert calls[1]["pinned_host_key"] == PinnedHostKey("ssh-ed25519", "SHA256:first")
    assert calls[1]["tofu_policy"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["deploy", "uninstall"])
async def test_changed_key_is_refused_with_error_code(client, db, device, ssh_calls, action):
    _, presented = ssh_calls
    db.add(SshKnownHost(host=device.ip, port=22, key_type="ssh-ed25519", fingerprint="SHA256:first", public_key="x"))
    await db.commit()
    presented["key"] = _FakeKey("SHA256:attacker")

    res = await client.post(f"/api/agent/{action}/{device.id}", json=LOGIN, headers=HEADERS)
    body = res.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "host_key_changed"
    assert "No credentials were sent" in body["message"]

    # The stored key stays as it is
    assert [k.fingerprint for k in await _known_hosts(db)] == ["SHA256:first"]


@pytest.mark.asyncio
async def test_strict_mode_uses_no_tofu(client, device, ssh_calls, monkeypatch):
    calls, _ = ssh_calls
    monkeypatch.setattr(settings, "ssh_strict_mode", True)
    res = await client.post(f"/api/agent/deploy/{device.id}", json=LOGIN, headers=HEADERS)
    assert res.json()["status"] == "failed"
    assert calls[0]["tofu_policy"] is None


def test_client_for_installs_tofu_or_pinned_policy():
    tofu = TofuHostKeyPolicy()
    with patch.object(settings, "ssh_strict_mode", False):
        assert agent_deployer._client_for(None, tofu)._policy is tofu
    with patch.object(settings, "ssh_strict_mode", True):
        assert isinstance(agent_deployer._client_for(None, tofu)._policy, paramiko.RejectPolicy)

    pinned_client = agent_deployer._client_for(PinnedHostKey("ssh-ed25519", "SHA256:first"), tofu)
    with pytest.raises(HostKeyNotTrusted):
        # Raised during the key exchange, before paramiko sends any password
        pinned_client._policy.missing_host_key(pinned_client, "192.168.1.70", _FakeKey("SHA256:attacker"))
