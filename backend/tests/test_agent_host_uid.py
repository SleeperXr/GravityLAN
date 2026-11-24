"""Tests for agent host-UID computation and TOFU host-identity pinning."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.models.agent import AgentToken, DeviceMetrics
from app.models.device import Device
from app.services.agent_tokens import hash_agent_token
from app.services.session_service import session_store
from app.services.stepup import store as stepup_store

ROOT = Path(__file__).resolve().parents[2]
HOST_UID_A = "sha256:" + "a" * 64
HOST_UID_B = "sha256:" + "b" * 64
HOST_UID_C = "sha256:" + "c" * 64
FINGERPRINT_B = "b" * 12  # what the overview shows for HOST_UID_B and the confirmation has to name
FINGERPRINT_C = "c" * 12


def _load_agent_module() -> Any:
    spec = importlib.util.spec_from_file_location("gravitylan_agent_host_uid", ROOT / "agent" / "gravitylan-agent.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _report_payload(device_id: int, *, host_uid: str | None = None, cpu: float = 12.5) -> dict[str, Any]:
    body: dict[str, Any] = {
        "device_id": device_id,
        "agent_version": "0.3.18",
        "timestamp": 1700000000.0,
        "cpu_percent": cpu,
        "ram": {"total_mb": 4096, "used_mb": 1024, "percent": 25.0},
        "disk": [],
        "network": {},
        "system": {},
    }
    if host_uid is not None:
        body["host_uid"] = host_uid
    return body


async def _seed_agent(db, *, ip: str = "192.168.100.3", raw_token: str = "agent-secret-token-123456") -> tuple[Device, AgentToken, str]:
    dev = Device(ip=ip, hostname="fedo", display_name="fedo", is_online=True, has_agent=True)
    db.add(dev)
    await db.flush()
    tok = AgentToken(device_id=dev.id, token=hash_agent_token(raw_token), is_active=True)
    db.add(tok)
    await db.commit()
    await db.refresh(dev)
    await db.refresh(tok)
    return dev, tok, raw_token


def _confirmed_session_cookie(area: str = "remote") -> str:
    session_id = session_store.create_session("pytest-agent")
    stepup_store.grant(session_id, area, 600)
    return session_id


# --- Agent-side compute_host_uid --------------------------------------------


def test_agent_compute_host_uid_combines_machine_id_and_product_uuid(tmp_path: Path) -> None:
    agent_mod = _load_agent_module()
    mid = tmp_path / "machine-id"
    puuid = tmp_path / "product_uuid"
    mid.write_text("0123456789abcdef0123456789abcdef\n", encoding="utf-8")
    puuid.write_text("11111111-2222-3333-4444-555555555555\n", encoding="utf-8")

    uid_both = agent_mod.compute_host_uid((str(mid),), str(puuid))
    assert uid_both is not None and uid_both.startswith("sha256:") and len(uid_both) == 71

    # Different product_uuid (e.g. cloned VM) produces a different host_uid
    puuid.write_text("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n", encoding="utf-8")
    uid_cloned = agent_mod.compute_host_uid((str(mid),), str(puuid))
    assert uid_cloned != uid_both

    # Missing product_uuid (e.g. LXC / SBC) still produces a stable host_uid from machine-id
    uid_mid_only = agent_mod.compute_host_uid((str(mid),), str(tmp_path / "missing"))
    assert uid_mid_only is not None and uid_mid_only.startswith("sha256:") and uid_mid_only != uid_both


def test_agent_compute_host_uid_ignores_placeholders_and_returns_none_when_missing(tmp_path: Path) -> None:
    agent_mod = _load_agent_module()
    puuid = tmp_path / "product_uuid"
    puuid.write_text("00000000-0000-0000-0000-000000000000\n", encoding="utf-8")
    assert agent_mod.compute_host_uid((str(tmp_path / "missing"),), str(puuid)) is None


# --- Backend TOFU pinning, mismatch 409, dismiss & adopt --------------------


@pytest.mark.asyncio
async def test_legacy_agent_without_host_uid_keeps_reporting(client, db) -> None:
    dev, tok, raw = await _seed_agent(db)
    res = await client.post(
        "/api/agent/report",
        json=_report_payload(dev.id, host_uid=None),
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert res.status_code == 200
    await db.refresh(tok)
    assert tok.host_uid is None
    assert tok.pending_host_uid is None


@pytest.mark.asyncio
async def test_invalid_host_uid_format_is_rejected_with_422(client, db) -> None:
    dev, _, raw = await _seed_agent(db)
    res = await client.post(
        "/api/agent/report",
        json=_report_payload(dev.id, host_uid="not-a-sha256"),
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_host_uid_tofu_pin_mismatch_dismiss_and_adopt_lifecycle(client, db, admin_token) -> None:
    dev, tok, raw = await _seed_agent(db)
    agent_headers = {"Authorization": f"Bearer {raw}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. First report with HOST_UID_A pins it via TOFU
    r1 = await client.post("/api/agent/report", json=_report_payload(dev.id, host_uid=HOST_UID_A, cpu=10.0), headers=agent_headers)
    assert r1.status_code == 200
    await db.refresh(tok)
    assert tok.host_uid == HOST_UID_A
    assert tok.pending_host_uid is None

    # 2. Matching host keeps reporting cleanly
    r2 = await client.post("/api/agent/report", json=_report_payload(dev.id, host_uid=HOST_UID_A, cpu=20.0), headers=agent_headers)
    assert r2.status_code == 200
    count_before = len((await db.execute(select(DeviceMetrics).where(DeviceMetrics.device_id == dev.id))).scalars().all())
    assert count_before == 2

    # 3. Different host (VM migration / clone) is rejected with 409 without writing metrics
    r_mismatch = await client.post("/api/agent/report", json=_report_payload(dev.id, host_uid=HOST_UID_B, cpu=99.0), headers=agent_headers)
    assert r_mismatch.status_code == 409
    await db.refresh(tok)
    assert tok.host_uid == HOST_UID_A
    assert tok.pending_host_uid == HOST_UID_B
    assert tok.pending_host_at is not None
    count_after_mismatch = len((await db.execute(select(DeviceMetrics).where(DeviceMetrics.device_id == dev.id))).scalars().all())
    assert count_after_mismatch == count_before

    # Overview exposes the pending host identity change
    overview = await client.get("/api/agent/overview", headers=admin_headers)
    assert overview.status_code == 200
    entry = next(a for a in overview.json()["agents"] if a["device_id"] == dev.id)
    assert entry["has_pending_host_uid"] is True

    # 4. Dismiss clears pending_host_uid while keeping HOST_UID_A pinned
    session_id = _confirmed_session_cookie("remote")
    session_cookies = {"gravitylan_token": session_id}
    r_dismiss = await client.post(f"/api/agent/dismiss-host/{dev.id}", cookies=session_cookies)
    assert r_dismiss.status_code == 200
    await db.refresh(tok)
    assert tok.host_uid == HOST_UID_A
    assert tok.pending_host_uid is None

    # HOST_UID_B is still rejected after dismiss and re-parks pending_host_uid
    r_mismatch_again = await client.post("/api/agent/report", json=_report_payload(dev.id, host_uid=HOST_UID_B), headers=agent_headers)
    assert r_mismatch_again.status_code == 409

    # 5. Adopt promotes HOST_UID_B to pinned host_uid; now HOST_UID_B succeeds and HOST_UID_A is rejected
    r_adopt = await client.post(f"/api/agent/adopt-host/{dev.id}", json={"pending": FINGERPRINT_B}, cookies=session_cookies)
    assert r_adopt.status_code == 200
    await db.refresh(tok)
    assert tok.host_uid == HOST_UID_B
    assert tok.pending_host_uid is None
    assert tok.pending_host_ip is None

    r_new_ok = await client.post("/api/agent/report", json=_report_payload(dev.id, host_uid=HOST_UID_B, cpu=33.0), headers=agent_headers)
    assert r_new_ok.status_code == 200
    r_old_rejected = await client.post("/api/agent/report", json=_report_payload(dev.id, host_uid=HOST_UID_A), headers=agent_headers)
    assert r_old_rejected.status_code == 409


async def _report(client, raw: str, device_id: int, host_uid: str | None, cpu: float = 12.5):
    return await client.post(
        "/api/agent/report", json=_report_payload(device_id, host_uid=host_uid, cpu=cpu),
        headers={"Authorization": f"Bearer {raw}"},
    )


async def _pin(client, raw: str, device_id: int, host_uid: str = HOST_UID_A) -> None:
    assert (await _report(client, raw, device_id, host_uid)).status_code == 200


async def _metric_count(db, device_id: int) -> int:
    return len((await db.execute(select(DeviceMetrics).where(DeviceMetrics.device_id == device_id))).scalars().all())


@pytest.mark.asyncio
async def test_a_pinned_token_rejects_a_report_without_host_uid(client, db) -> None:
    """Leaving the field out must not get around the pin: only the host knows its own identity."""
    dev, tok, raw = await _seed_agent(db)
    await _pin(client, raw, dev.id)
    before = await _metric_count(db, dev.id)

    response = await _report(client, raw, dev.id, None, cpu=77.0)

    assert response.status_code == 409
    assert "no host identity" in response.json()["detail"]
    assert await _metric_count(db, dev.id) == before
    await db.refresh(tok)
    assert (tok.host_uid, tok.pending_host_uid) == (HOST_UID_A, None)  # nothing to confirm: no host named itself


@pytest.mark.asyncio
async def test_a_foreign_host_reporting_again_writes_nothing_new(client, db) -> None:
    dev, tok, raw = await _seed_agent(db)
    await _pin(client, raw, dev.id)

    assert (await _report(client, raw, dev.id, HOST_UID_B)).status_code == 409
    await db.refresh(tok)
    first_seen, first_ip = tok.pending_host_at, tok.pending_host_ip
    assert first_seen is not None and first_ip

    assert (await _report(client, raw, dev.id, HOST_UID_B)).status_code == 409

    await db.refresh(tok)
    assert (tok.pending_host_at, tok.pending_host_ip, tok.pending_host_uid) == (first_seen, first_ip, HOST_UID_B)


@pytest.mark.asyncio
async def test_a_second_foreign_host_replaces_the_pending_one_and_the_first_cannot_be_confirmed(client, db, admin_token) -> None:
    dev, tok, raw = await _seed_agent(db)
    await _pin(client, raw, dev.id)
    assert (await _report(client, raw, dev.id, HOST_UID_B)).status_code == 409
    assert (await _report(client, raw, dev.id, HOST_UID_C)).status_code == 409
    cookies = {"gravitylan_token": _confirmed_session_cookie("remote")}

    # The admin looked at host B; host C has taken its place since
    stale = await client.post(f"/api/agent/adopt-host/{dev.id}", json={"pending": FINGERPRINT_B}, cookies=cookies)
    assert stale.status_code == 409
    await db.refresh(tok)
    assert (tok.host_uid, tok.pending_host_uid) == (HOST_UID_A, HOST_UID_C)

    current = await client.post(f"/api/agent/adopt-host/{dev.id}", json={"pending": FINGERPRINT_C}, cookies=cookies)
    assert current.status_code == 200
    await db.refresh(tok)
    assert (tok.host_uid, tok.pending_host_uid) == (HOST_UID_C, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, {}, {"pending": "nope"}, {"pending": "B" * 12}, {"pending": "b" * 64}])
async def test_confirming_a_host_must_name_its_fingerprint(client, db, admin_token, body) -> None:
    dev, tok, raw = await _seed_agent(db)
    await _pin(client, raw, dev.id)
    assert (await _report(client, raw, dev.id, HOST_UID_B)).status_code == 409
    cookies = {"gravitylan_token": _confirmed_session_cookie("remote")}

    response = await client.post(f"/api/agent/adopt-host/{dev.id}", json=body, cookies=cookies)

    assert response.status_code == 422
    await db.refresh(tok)
    assert (tok.host_uid, tok.pending_host_uid) == (HOST_UID_A, HOST_UID_B)


@pytest.mark.asyncio
async def test_the_overview_names_the_pending_host_by_address_and_fingerprint(client, db, admin_token) -> None:
    dev, tok, raw = await _seed_agent(db)
    await _pin(client, raw, dev.id)
    assert (await _report(client, raw, dev.id, HOST_UID_B)).status_code == 409
    await db.refresh(tok)

    overview = await client.get("/api/agent/overview", headers={"Authorization": f"Bearer {admin_token}"})

    entry = next(a for a in overview.json()["agents"] if a["device_id"] == dev.id)
    assert entry["pending_host_fingerprint"] == FINGERPRINT_B
    assert entry["pending_host_ip"] == tok.pending_host_ip and tok.pending_host_ip
    assert "pending_host_uid" not in entry and HOST_UID_B not in str(entry)  # the full identity never leaves the server


@pytest.mark.asyncio
async def test_dismissing_forgets_the_pending_address_too(client, db, admin_token) -> None:
    dev, tok, raw = await _seed_agent(db)
    await _pin(client, raw, dev.id)
    assert (await _report(client, raw, dev.id, HOST_UID_B)).status_code == 409
    cookies = {"gravitylan_token": _confirmed_session_cookie("remote")}

    assert (await client.post(f"/api/agent/dismiss-host/{dev.id}", cookies=cookies)).status_code == 200

    await db.refresh(tok)
    assert (tok.host_uid, tok.pending_host_uid, tok.pending_host_at, tok.pending_host_ip) == (HOST_UID_A, None, None, None)


@pytest.mark.asyncio
async def test_resetting_the_pin_clears_the_host_and_everything_waiting(db) -> None:
    """A new token or agent configuration starts over: the next report pins again."""
    _, tok, _ = await _seed_agent(db)
    tok.host_uid, tok.pending_host_uid = HOST_UID_A, HOST_UID_B
    tok.pending_host_at, tok.pending_host_ip = tok.last_seen, "192.168.100.9"

    tok.reset_host_pin()

    assert (tok.host_uid, tok.pending_host_uid, tok.pending_host_at, tok.pending_host_ip) == (None, None, None, None)
