"""Before the setup is completed the wizard's routes need no login: what they may do is bounded."""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.api import scanner
from app.models.setting import Setting
from app.schemas.network import is_setup_scan_target


@pytest.fixture(autouse=True)
def reset_scan_state():
    """The scan state is module-global; give every test a fresh one."""
    original = scanner.state
    scanner.state = scanner.ScanStateManager()
    yield
    scanner.state = original


@pytest.mark.parametrize("cidr, allowed", [
    ("192.168.1.0/24", True),
    ("10.20.0.0/16", True),
    ("172.31.255.0/24", True),
    ("100.64.0.0/16", True),
    ("8.8.8.0/24", False),
    ("172.32.0.0/24", False),
    ("127.0.0.0/24", False),
    ("169.254.0.0/16", False),
])
def test_setup_scan_targets_are_private_ranges(cidr, allowed):
    assert is_setup_scan_target(cidr) is allowed


@pytest.mark.asyncio
async def test_public_subnet_refused_before_setup(client):
    with patch.object(scanner, "run_planner_scan", AsyncMock(return_value=0)) as run:
        res = await client.post("/api/scanner/start", json={"subnets": ["192.168.1.0/24", "8.8.8.0/24"]})
    assert res.status_code == 403
    assert "8.8.8.0/24" in res.json()["detail"]
    run.assert_not_called()
    assert await scanner.state.get_active() is False


@pytest.mark.asyncio
async def test_empty_subnet_list_refused_before_setup(client):
    # Without named subnets the scan would fall back to the auto-detected ones unchecked
    with patch.object(scanner, "run_planner_scan", AsyncMock(return_value=0)) as run:
        res = await client.post("/api/scanner/start", json={"subnets": []})
    assert res.status_code == 403
    run.assert_not_called()
    assert await scanner.state.get_active() is False


@pytest.mark.asyncio
async def test_private_subnet_still_scans_before_setup(client):
    with patch.object(scanner, "run_planner_scan", AsyncMock(return_value=0)) as run:
        res = await client.post("/api/scanner/start", json={"subnets": ["192.168.1.0/24"]})
        assert res.status_code == 200
        await scanner.state.task
    run.assert_awaited_once()
    assert run.await_args.args[0] == ["192.168.1.0/24"]


@pytest.mark.asyncio
async def test_public_subnet_scans_after_setup(client, admin_token):
    with patch.object(scanner, "run_planner_scan", AsyncMock(return_value=0)) as run:
        res = await client.post(
            "/api/scanner/start", json={"subnets": ["8.8.8.0/24"]},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert res.status_code == 200
        await scanner.state.task
    run.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"admin_password": ""}, {"admin_password": "1234567"}])
async def test_setup_needs_a_password_of_eight_characters(client, db, payload):
    res = await client.post("/api/setup/complete", json=payload)
    assert res.status_code == 422
    done = (await db.execute(select(Setting).where(Setting.key == "setup.complete"))).scalar_one_or_none()
    assert done is None
