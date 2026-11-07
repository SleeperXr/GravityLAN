"""Endpoint tests for app.api.scanner: manual IP scan, discovered hosts, scan jobs, live discovery, WebSocket."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import scanner
from app.models.device import DiscoveredHost
from app.models.network import Subnet
from app.models.setting import Setting
from app.schemas.device import DiscoveredHostUpdate
from app.schemas.scan import ScanProgress, ScanRequest, ScanStatus
from app.services.cache_service import discovery_cache


@pytest.fixture(autouse=True)
def reset_scan_state():
    """The scan state and the discovery cache are module-global; every test starts fresh."""
    original = scanner.state
    scanner.state = scanner.ScanStateManager()
    discovery_cache.invalidate()
    yield
    scanner.state = original
    discovery_cache.invalidate()


@pytest.fixture
def session(monkeypatch, db):
    """The endpoints open their own session; hand them the test database instead."""

    @asynccontextmanager
    async def fake_session():
        yield db

    monkeypatch.setattr(scanner, "async_session", fake_session)
    return db


class _FakeWs:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    async def send_json(self, data):
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(data)


# --- ScanStateManager ---------------------------------------------------------

@pytest.mark.asyncio
async def test_broadcast_reaches_clients_and_drops_the_broken_ones():
    good, broken = _FakeWs(), _FakeWs(fail=True)
    await scanner.state.add_client(good)
    await scanner.state.add_client(broken)

    progress = ScanProgress(status=ScanStatus.RUNNING, message="hi")
    await scanner.state.broadcast(progress)

    assert good.sent[0]["message"] == "hi"
    assert scanner.state.ws_clients == [good]
    assert scanner.state.last_progress is progress


@pytest.mark.asyncio
async def test_remove_and_detach_clients():
    a, b = _FakeWs(), _FakeWs()
    await scanner.state.add_client(a)
    await scanner.state.add_client(b)

    await scanner.state.remove_client(a)
    await scanner.state.remove_client(a)  # a second removal is harmless
    assert scanner.state.ws_clients == [b]

    assert await scanner.state.detach_all_clients() == [b]
    assert scanner.state.ws_clients == []


# --- simple endpoints ----------------------------------------------------------

@pytest.mark.asyncio
async def test_test_endpoint_and_idle_status():
    assert await scanner.test_scanner() == {"status": "ok", "module": "scanner"}
    status = await scanner.get_scan_status()
    assert status.status == ScanStatus.IDLE


@pytest.mark.asyncio
async def test_status_returns_the_last_progress():
    scanner.state.last_progress = ScanProgress(status=ScanStatus.RUNNING, message="busy")
    assert (await scanner.get_scan_status()).message == "busy"


@pytest.mark.asyncio
async def test_get_subnets_lists_the_local_subnets(monkeypatch):
    monkeypatch.setattr(scanner, "get_local_subnets", lambda: ["sentinel"])
    assert await scanner.get_subnets() == ["sentinel"]


@pytest.mark.asyncio
async def test_stop_sets_the_cancel_event():
    assert await scanner.stop_scan() == {"status": "cancelling"}
    assert scanner.state.cancel_event.is_set()


# --- scan-ip -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_ip_rejects_an_invalid_address():
    with pytest.raises(HTTPException) as exc:
        await scanner.scan_ip("300.1.1.1")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_scan_ip_uses_nmap_with_the_configured_dns_server(monkeypatch, session):
    session.add(Setting(key="dns.server", value="192.168.1.2"))
    await session.commit()
    nmap = AsyncMock(return_value=[{"port": 22}])
    fallback = AsyncMock()
    monkeypatch.setattr(scanner, "nmap_scan", nmap)
    monkeypatch.setattr(scanner, "scan_ports", fallback)

    res = await scanner.scan_ip("192.168.1.10")

    assert res["ip"] == "192.168.1.10"
    assert res["ports"] == [{"port": 22}]
    assert nmap.await_args.kwargs["dns_server"] == "192.168.1.2"
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_scan_ip_falls_back_to_the_socket_scan(monkeypatch, session):
    monkeypatch.setattr(scanner, "nmap_scan", AsyncMock(return_value=[]))
    fallback = AsyncMock(return_value=[{"port": 80}])
    monkeypatch.setattr(scanner, "scan_ports", fallback)

    res = await scanner.scan_ip("192.168.1.10")

    assert res["ports"] == [{"port": 80}]
    assert fallback.await_args.kwargs == {"gentle": False, "timeout": 0.5}


# --- quick-subnet-scan / discover ----------------------------------------------

@pytest.mark.asyncio
async def test_quick_subnet_scan_expands_bare_prefixes(monkeypatch):
    planner = AsyncMock(return_value=0)
    monkeypatch.setattr(scanner, "run_planner_scan", planner)

    res = await scanner.quick_subnet_scan("192.168.1, 10.0.0.0/24,")

    assert res["status"] == "ok"
    assert planner.await_args.args[0] == ["192.168.1.0/24", "10.0.0.0/24"]
    assert planner.await_args.kwargs == {"announce": False}


def test_normalize_subnet_input():
    assert scanner._normalize_subnet_input("10.0.0.0/16") == "10.0.0.0/16"
    assert scanner._normalize_subnet_input("192.168.1") == "192.168.1.0/24"
    assert scanner._normalize_subnet_input("192.168.1.0") == "192.168.1.0/24"


@pytest.mark.asyncio
async def test_discover_starts_a_planner_scan(monkeypatch):
    monkeypatch.setattr(scanner, "run_planner_scan", AsyncMock(return_value=3))
    res = await scanner.discover_subnet(ScanRequest(subnets=["10.0.0.0/24"]))
    assert res["message"] == "Planner scan started"
    await scanner.state.task
    assert scanner.state.last_progress.status == ScanStatus.COMPLETED


# --- discovered hosts ------------------------------------------------------------

@pytest.mark.asyncio
async def test_discovered_hosts_lists_online_or_monitored_monitored_first(session):
    now = datetime(2026, 11, 1, 12, 0)
    session.add_all([
        DiscoveredHost(ip="10.0.0.1", is_online=True, last_seen=now),
        DiscoveredHost(ip="10.0.0.2", is_online=True, last_seen=now + timedelta(minutes=5)),
        DiscoveredHost(ip="10.0.0.3", is_online=False, is_monitored=True, last_seen=now - timedelta(days=1)),
        DiscoveredHost(ip="10.0.0.4", is_online=False, last_seen=now),
    ])
    await session.commit()

    hosts = await scanner.get_discovered_hosts()

    assert [h.ip for h in hosts] == ["10.0.0.3", "10.0.0.2", "10.0.0.1"]
    assert discovery_cache.get_hosts() == hosts


@pytest.mark.asyncio
async def test_discovered_hosts_come_from_the_cache_when_present(monkeypatch):
    discovery_cache.set_hosts(["cached"])

    @asynccontextmanager
    async def no_session():
        raise AssertionError("the database must not be asked")
        yield

    monkeypatch.setattr(scanner, "async_session", no_session)
    assert await scanner.get_discovered_hosts() == ["cached"]


@pytest.mark.asyncio
async def test_patch_discovered_host_changes_only_the_sent_fields(session):
    host = DiscoveredHost(ip="10.0.0.5", is_online=True, custom_name="old", is_monitored=False)
    session.add(host)
    await session.commit()
    discovery_cache.set_hosts(["stale"])

    updated = await scanner.patch_discovered_host(host.id, DiscoveredHostUpdate(is_monitored=True))

    assert updated.is_monitored is True
    assert updated.custom_name == "old"
    assert discovery_cache.get_hosts() is None


@pytest.mark.asyncio
async def test_patch_and_delete_unknown_host_are_404(session):
    with pytest.raises(HTTPException) as exc_patch:
        await scanner.patch_discovered_host(9999, DiscoveredHostUpdate(custom_name="x"))
    assert exc_patch.value.status_code == 404

    with pytest.raises(HTTPException) as exc_delete:
        await scanner.delete_discovered_host(9999)
    assert exc_delete.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_discovered_host(session):
    host = DiscoveredHost(ip="10.0.0.6", is_online=True)
    session.add(host)
    await session.commit()
    discovery_cache.set_hosts(["stale"])

    res = await scanner.delete_discovered_host(host.id)

    assert res["status"] == "success"
    assert await session.get(DiscoveredHost, host.id) is None
    assert discovery_cache.get_hosts() is None


@pytest.mark.asyncio
async def test_refresh_keeps_a_known_mac_and_name_when_nothing_new_is_found(monkeypatch, session):
    host = DiscoveredHost(ip="10.0.0.7", is_online=True, hostname="nas", mac="aa:bb:cc:dd:ee:ff", vendor="Old")
    session.add(host)
    await session.commit()
    macs = AsyncMock()
    monkeypatch.setattr(scanner, "resolve_hostname", AsyncMock(return_value=None))
    monkeypatch.setattr(scanner, "resolve_mac_addresses", macs)
    monkeypatch.setattr(scanner, "get_vendor", lambda mac: None)

    refreshed = await scanner.refresh_discovered_host(host.id)

    assert refreshed.hostname == "nas"
    assert refreshed.vendor == "Old"
    macs.assert_not_awaited()


# --- scan jobs ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_second_scan_is_refused_while_one_runs():
    await scanner.state.set_active(True)
    assert (await scanner.start_scan(ScanRequest()))["status"] == "error"
    assert (await scanner.start_dashboard_scan_api(ScanRequest(), background_tasks=None))["status"] == "error"


@pytest.mark.asyncio
async def test_planner_scan_reports_host_counts_and_device_events(monkeypatch):
    seen = []
    original = scanner.state.broadcast

    async def record(progress):
        seen.append(progress)
        await original(progress)

    monkeypatch.setattr(scanner.state, "broadcast", record)

    async def fake_planner(subnets, progress_callback, hosts_callback):
        await hosts_callback("10.0.0.0/24", 64, 256)
        await progress_callback("EVENT:RELOAD_DEVICES")
        await progress_callback("probing")
        return 2

    monkeypatch.setattr(scanner, "run_planner_scan", fake_planner)

    await scanner.start_scan(ScanRequest(subnets=["10.0.0.0/24"]))
    await scanner.state.task

    hosts_update = seen[1]
    assert (hosts_update.current_subnet, hosts_update.hosts_scanned, hosts_update.hosts_total) == ("10.0.0.0/24", 64, 256)
    assert hosts_update.progress == 25.0
    assert seen[2].status == ScanStatus.DEVICES_UPDATED
    assert seen[2].message == "Host discovered..."
    assert seen[3].message == "probing"
    assert seen[-1].status == ScanStatus.COMPLETED
    assert seen[-1].devices_found == 2
    assert await scanner.state.get_active() is False


@pytest.mark.asyncio
async def test_dashboard_scan_without_subnets_uses_the_enabled_ones(monkeypatch, session):
    monkeypatch.setattr(scanner, "get_scan_subnets", AsyncMock(return_value=["192.168.1.0/24"]))
    seen_subnets = []

    async def fake_dashboard(subnets, progress_callback):
        seen_subnets.extend(subnets)
        await progress_callback("EVENT:RELOAD_DEVICES")
        return 4

    monkeypatch.setattr(scanner, "run_dashboard_scan", fake_dashboard)

    await scanner.start_dashboard_scan_api(ScanRequest(), background_tasks=None)
    await scanner.state.task

    assert seen_subnets == ["192.168.1.0/24"]
    assert scanner.state.last_progress.status == ScanStatus.COMPLETED
    assert scanner.state.last_progress.devices_found == 4
    assert "4 devices" in scanner.state.last_progress.message


# --- live discovery ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_discovery_uses_the_subnet_dns_and_skips_a_failing_subnet(monkeypatch, session):
    session.add(Setting(key="dns.server", value="192.168.1.2"))
    session.add(Subnet(cidr="10.0.1.0/24", name="Lab", dns_server="10.0.1.53"))
    await session.commit()

    dns_used = {}

    async def fake_discover(ips, dns_server, timeout):
        subnet = ips[0].rsplit(".", 1)[0]
        dns_used[subnet] = dns_server
        if subnet == "10.0.3":
            raise RuntimeError("icmp blocked")
        if subnet == "10.0.2":
            return []
        return [{"ip": f"{subnet}.5"}]

    async def fake_macs(hosts):
        for h in hosts:
            h["mac"] = "aa:aa:aa:aa:aa:aa"
        return hosts

    async def fake_names(hosts, dns_server):
        for h in hosts:
            h["hostname"] = "host-" + h["ip"]

    sync = AsyncMock()
    macs = AsyncMock(side_effect=fake_macs)
    monkeypatch.setattr(scanner, "discover_hosts_simple", fake_discover)
    monkeypatch.setattr(scanner, "resolve_mac_addresses", macs)
    monkeypatch.setattr(scanner, "resolve_hostnames", fake_names)
    monkeypatch.setattr(scanner, "sync_host_to_db", sync)

    hosts = await scanner.live_discovery("10.0.1.0/24,10.0.3.0/24,10.0.2.0/24")

    assert [h["ip"] for h in hosts] == ["10.0.1.5"]
    assert dns_used == {"10.0.1": "10.0.1.53", "10.0.3": "192.168.1.2", "10.0.2": "192.168.1.2"}
    macs.assert_awaited_once()  # an empty subnet resolves nothing
    sync.assert_awaited_once_with(ip="10.0.1.5", mac="aa:aa:aa:aa:aa:aa", hostname="host-10.0.1.5", vendor=None)


# --- WebSocket -------------------------------------------------------------------------

def _ws_app():
    app = FastAPI()
    app.include_router(scanner.router)
    return app


def test_websocket_registers_and_removes_the_client(monkeypatch):
    monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", AsyncMock(return_value={"level": "session"}))
    client = TestClient(_ws_app())

    with client.websocket_connect("/api/scanner/ws") as ws:
        ws.send_text("ping")
        assert len(scanner.state.ws_clients) == 1

    # The disconnect is handled on the server side after the client leaves
    client.close()
    assert scanner.state.ws_clients == []


def test_websocket_without_authorization_is_not_accepted(monkeypatch):
    async def refuse(websocket, **kwargs):
        # Like the real check: it closes the connection itself and returns None
        await websocket.close(code=4003, reason="Unauthorized")
        return None

    monkeypatch.setattr("app.api.auth.authenticate_websocket_authorized", refuse)
    client = TestClient(_ws_app())

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/scanner/ws"):
            pass
    assert exc.value.code == 4003
    assert scanner.state.ws_clients == []
