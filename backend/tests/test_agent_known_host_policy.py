"""_known_host_policy (app/api/agent.py): which host key a typed-in agent login pins or learns."""

import app.api.agent as agent_api
from app.models.ssh import SshKnownHost
from app.services.ssh_utils import PinnedHostKey, TofuHostKeyPolicy


async def test_a_stored_key_is_pinned(db):
    db.add(SshKnownHost(host="192.0.2.10", port=22, key_type="ssh-ed25519", fingerprint="SHA256:abc", public_key="ssh-ed25519 AAAA"))
    await db.commit()
    pinned, tofu = await agent_api._known_host_policy(db, "192.0.2.10", 22)
    assert pinned == PinnedHostKey(key_type="ssh-ed25519", fingerprint="SHA256:abc")
    assert tofu is None


async def test_an_unknown_host_learns_its_first_key(db, monkeypatch):
    monkeypatch.setattr(agent_api.settings, "ssh_strict_mode", False)
    pinned, tofu = await agent_api._known_host_policy(db, "192.0.2.10", 2222)
    assert pinned is None and isinstance(tofu, TofuHostKeyPolicy)


async def test_strict_mode_learns_nothing(db, monkeypatch):
    monkeypatch.setattr(agent_api.settings, "ssh_strict_mode", True)
    assert await agent_api._known_host_policy(db, "192.0.2.10", 22) == (None, None)
