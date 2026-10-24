"""Tests for the scan job state in app.api.scanner."""

from unittest.mock import AsyncMock, patch

import pytest

from app.api import scanner
from app.schemas.scan import ScanRequest, ScanStatus


@pytest.fixture(autouse=True)
def reset_scan_state():
    """The scan state is module-global; give every test a fresh one."""
    original = scanner.state
    scanner.state = scanner.ScanStateManager()
    yield
    scanner.state = original


@pytest.mark.asyncio
async def test_failed_planner_scan_reports_failed_and_frees_the_slot():
    with patch.object(scanner, "run_planner_scan", AsyncMock(side_effect=RuntimeError("nmap missing"))):
        res = await scanner.start_scan(ScanRequest(subnets=["10.0.0.0/24"]))
        assert res["status"] == "ok"
        await scanner.state.task

    assert scanner.state.last_progress.status == ScanStatus.FAILED
    assert "nmap missing" in scanner.state.last_progress.message
    assert await scanner.state.get_active() is False


@pytest.mark.asyncio
async def test_failed_dashboard_scan_reports_failed_and_frees_the_slot():
    with patch.object(scanner, "run_dashboard_scan", AsyncMock(side_effect=RuntimeError("boom"))):
        res = await scanner.start_dashboard_scan_api(ScanRequest(subnets=["10.0.0.0/24"]), background_tasks=None)
        assert res["status"] == "ok"
        await scanner.state.task

    assert scanner.state.last_progress.status == ScanStatus.FAILED
    assert "boom" in scanner.state.last_progress.message
    assert await scanner.state.get_active() is False


@pytest.mark.asyncio
async def test_refresh_discovered_host_fills_name_mac_and_vendor(monkeypatch, db):
    from contextlib import asynccontextmanager
    from app.models.device import DiscoveredHost

    host = DiscoveredHost(ip="192.168.100.84", is_online=True)
    db.add(host)
    await db.commit()

    @asynccontextmanager
    async def fake_session():
        yield db

    async def fake_macs(hosts, *args, **kwargs):
        hosts[0]["mac"] = "60:74:f4:28:79:f6"
        return hosts

    resolve = AsyncMock(return_value="xiaomi-vacuum.local")
    monkeypatch.setattr(scanner, "async_session", fake_session)
    monkeypatch.setattr(scanner, "resolve_hostname", resolve)
    monkeypatch.setattr(scanner, "resolve_mac_addresses", fake_macs)
    monkeypatch.setattr(scanner, "get_vendor", lambda mac: "Xiaomi")

    refreshed = await scanner.refresh_discovered_host(host.id)

    assert refreshed.hostname == "xiaomi-vacuum.local"
    assert refreshed.mac == "60:74:f4:28:79:f6"
    assert refreshed.vendor == "Xiaomi"
    # A refresh the user asked for always looks again instead of answering from the cache
    assert resolve.await_args.kwargs["use_cache"] is False


@pytest.mark.asyncio
async def test_refresh_discovered_host_unknown_id_is_404(monkeypatch, db):
    from contextlib import asynccontextmanager
    from fastapi import HTTPException

    @asynccontextmanager
    async def fake_session():
        yield db

    monkeypatch.setattr(scanner, "async_session", fake_session)
    with pytest.raises(HTTPException) as exc:
        await scanner.refresh_discovered_host(99999)
    assert exc.value.status_code == 404
