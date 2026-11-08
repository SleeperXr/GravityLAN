"""The background loops of app/scanner/scheduler.py: what each one runs, how long it sleeps,
and how it backs off on errors or stops on cancellation. asyncio.sleep is replaced by a recorder
that ends the loop after a given number of sleeps."""

import asyncio
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.scanner.scheduler as scheduler_module


@pytest.fixture
def sched():
    s = scheduler_module.ScanScheduler()
    s._running = True
    return s


@pytest.fixture
def no_db(monkeypatch):
    """The loops open a session only to hand it to helpers the tests replace."""
    @asynccontextmanager
    async def fake_session():
        yield MagicMock()

    monkeypatch.setattr(scheduler_module, "async_session", fake_session)


def stop_after(monkeypatch, sched, n: int) -> list:
    """Record every sleep and stop the loop after the n-th one."""
    sleeps: list = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= n:
            sched._running = False

    monkeypatch.setattr(scheduler_module.asyncio, "sleep", sleep)
    return sleeps


def setup_states(monkeypatch, sched, *states: bool) -> None:
    monkeypatch.setattr(sched, "_is_setup_complete", AsyncMock(side_effect=list(states)))


# --- full scan -----------------------------------------------------------------------------------

async def test_full_scan_waits_for_setup(monkeypatch, sched):
    setup_states(monkeypatch, sched, False)
    scan = AsyncMock()
    monkeypatch.setattr(scheduler_module, "run_dashboard_scan", scan)
    sleeps = stop_after(monkeypatch, sched, 1)
    await sched._loop()
    scan.assert_not_called()
    assert sleeps == [10]


async def test_full_scan_runs_and_sleeps_the_interval(monkeypatch, sched, no_db):
    setup_states(monkeypatch, sched, True, True)
    monkeypatch.setattr(scheduler_module, "_get_setting_int", AsyncMock(return_value=5))
    monkeypatch.setattr(scheduler_module, "_get_scan_subnets", AsyncMock(side_effect=[["192.0.2.0/24"], []]))
    monkeypatch.setattr(scheduler_module, "_get_auto_scan_subnets", lambda: [])
    scan = AsyncMock()
    monkeypatch.setattr(scheduler_module, "run_dashboard_scan", scan)
    sleeps = stop_after(monkeypatch, sched, 2)

    await sched._loop()

    # Second round finds no subnets: no scan, but still the full interval
    scan.assert_awaited_once_with(["192.0.2.0/24"])
    assert sleeps == [300, 300]


async def test_full_scan_backs_off_a_minute_on_errors(monkeypatch, sched, no_db):
    setup_states(monkeypatch, sched, True)
    monkeypatch.setattr(scheduler_module, "_get_setting_int", AsyncMock(side_effect=RuntimeError("db locked")))
    sleeps = stop_after(monkeypatch, sched, 1)
    await sched._loop()
    assert sleeps == [60]


# --- ARP ------------------------------------------------------------------------------------------

async def test_arp_loop_scans_every_ten_seconds_and_survives_errors(monkeypatch, sched):
    setup_states(monkeypatch, sched, False, True, True)
    scan = AsyncMock(side_effect=[None, RuntimeError("no arp table")])
    monkeypatch.setattr(scheduler_module, "run_arp_only_scan", scan)
    sleeps = stop_after(monkeypatch, sched, 3)

    await sched._arp_loop()

    assert scan.await_count == 2
    assert sleeps == [10, 10, 10]


# --- quick scan -----------------------------------------------------------------------------------

async def test_quick_loop_waits_and_backs_off(monkeypatch, sched, no_db):
    setup_states(monkeypatch, sched, False, True, True)
    # 0 turns the quick scan off, then the settings read fails
    monkeypatch.setattr(scheduler_module, "_get_setting_int", AsyncMock(side_effect=[0, RuntimeError("db locked")]))
    monkeypatch.setattr(scheduler_module, "_get_scan_subnets", AsyncMock(return_value=[]))
    monkeypatch.setattr(scheduler_module, "_get_auto_scan_subnets", lambda: [])
    scan = AsyncMock()
    monkeypatch.setattr(scheduler_module, "run_planner_scan", scan)
    sleeps = stop_after(monkeypatch, sched, 3)

    await sched._quick_loop()

    scan.assert_not_called()
    assert sleeps == [10, 60, 60]


async def test_quick_loop_stops_when_cancelled(monkeypatch, sched, no_db):
    setup_states(monkeypatch, sched, True)
    monkeypatch.setattr(scheduler_module, "_get_setting_int", AsyncMock(return_value=300))
    monkeypatch.setattr(scheduler_module, "_get_scan_subnets", AsyncMock(return_value=["192.0.2.0/24"]))
    monkeypatch.setattr(scheduler_module, "_get_auto_scan_subnets", lambda: [])
    monkeypatch.setattr(scheduler_module, "run_planner_scan", AsyncMock(side_effect=asyncio.CancelledError))
    sleeps = stop_after(monkeypatch, sched, 99)

    await sched._quick_loop()

    assert sleeps == []


# --- Docker ---------------------------------------------------------------------------------------

@pytest.fixture
def docker(monkeypatch):
    from app.services.docker_service import docker_service

    state = {"available": True, "containers": [{"name": "web"}]}
    monkeypatch.setattr(docker_service, "is_available", lambda: state["available"])
    monkeypatch.setattr(docker_service, "get_local_containers", lambda: state["containers"])
    sync = AsyncMock()
    monkeypatch.setattr("app.scanner.sync.sync_docker_containers", sync)
    state["sync"] = sync
    return state


async def test_docker_loop_syncs_local_containers(monkeypatch, sched, docker):
    setup_states(monkeypatch, sched, False, True, True)
    docker["sync"].side_effect = [None, RuntimeError("socket gone")]
    sleeps = stop_after(monkeypatch, sched, 3)

    await sched._docker_loop()

    assert [c.args for c in docker["sync"].await_args_list] == [([{"name": "web"}],)] * 2
    assert sleeps == [10, 60, 60]


@pytest.mark.parametrize("available, containers", [(False, [{"name": "web"}]), (True, [])])
async def test_docker_loop_skips_without_docker_or_containers(monkeypatch, sched, docker, available, containers):
    docker.update(available=available, containers=containers)
    setup_states(monkeypatch, sched, True)
    sleeps = stop_after(monkeypatch, sched, 1)

    await sched._docker_loop()

    docker["sync"].assert_not_called()
    assert sleeps == [60]


async def test_docker_loop_stops_when_cancelled(monkeypatch, sched, docker):
    docker["sync"].side_effect = asyncio.CancelledError
    setup_states(monkeypatch, sched, True)
    sleeps = stop_after(monkeypatch, sched, 99)
    await sched._docker_loop()
    assert sleeps == []


# --- telemetry maintenance ------------------------------------------------------------------------

async def test_telemetry_maintenance_logs_only_what_changed(monkeypatch, sched, no_db, caplog):
    monkeypatch.setattr(
        "app.services.telemetry_rollups.run_telemetry_maintenance",
        AsyncMock(return_value={"hourly": 2, "pruned": 0}),
    )
    with caplog.at_level(logging.INFO, logger=scheduler_module.__name__):
        await sched._telemetry_maintenance()
    assert "{'hourly': 2}" in caplog.text


async def test_telemetry_maintenance_swallows_errors_but_not_cancellation(monkeypatch, sched, no_db):
    run = AsyncMock(side_effect=RuntimeError("telemetry.db locked"))
    monkeypatch.setattr("app.services.telemetry_rollups.run_telemetry_maintenance", run)
    await sched._telemetry_maintenance()

    run.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await sched._telemetry_maintenance()


# --- health probe ---------------------------------------------------------------------------------

async def test_health_probe_loop_interval_floor_and_fallbacks(monkeypatch, sched, no_db):
    setup_states(monkeypatch, sched, False, True, True)
    probe = AsyncMock(side_effect=[None, RuntimeError("probe broke")])
    monkeypatch.setattr("app.scanner.health_probe.run_health_probe_pass", probe)
    # 5 s is below the 15 s floor; then the interval cannot be read
    monkeypatch.setattr(scheduler_module, "_get_setting_int", AsyncMock(side_effect=[5, RuntimeError("db locked")]))
    sleeps = stop_after(monkeypatch, sched, 3)

    await sched._health_probe_loop()

    assert probe.await_count == 2
    assert sleeps == [10, 15, 60]


async def test_health_probe_loop_stops_when_the_probe_is_cancelled(monkeypatch, sched):
    setup_states(monkeypatch, sched, True)
    monkeypatch.setattr("app.scanner.health_probe.run_health_probe_pass", AsyncMock(side_effect=asyncio.CancelledError))
    sleeps = stop_after(monkeypatch, sched, 99)
    await sched._health_probe_loop()
    assert sleeps == []


async def test_health_probe_loop_stops_when_its_sleep_is_cancelled(monkeypatch, sched, no_db):
    setup_states(monkeypatch, sched, True)
    monkeypatch.setattr("app.scanner.health_probe.run_health_probe_pass", AsyncMock())
    monkeypatch.setattr(scheduler_module, "_get_setting_int", AsyncMock(return_value=60))
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))
    await sched._health_probe_loop()
    assert sched._running is True  # left by break, not by the flag


# --- notification outbox --------------------------------------------------------------------------

async def test_outbox_loop_retries_every_fifteen_seconds(monkeypatch, sched):
    process = AsyncMock(side_effect=[None, RuntimeError("smtp down")])
    monkeypatch.setattr("app.services.webhook_service.process_outbox", process)
    sleeps = stop_after(monkeypatch, sched, 2)

    await sched._outbox_loop()

    assert process.await_count == 2
    assert sleeps == [15, 15]


async def test_outbox_loop_stops_when_cancelled(monkeypatch, sched):
    process = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr("app.services.webhook_service.process_outbox", process)
    sleeps = stop_after(monkeypatch, sched, 99)
    await sched._outbox_loop()
    assert sleeps == []

    process.side_effect = None
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))
    await sched._outbox_loop()
    assert process.await_count == 2


# --- history cleanup ------------------------------------------------------------------------------

async def test_clean_old_history_reports_pruned_audit_entries(monkeypatch, sched, no_db, caplog):
    monkeypatch.setattr(scheduler_module, "_get_retention_days", AsyncMock(return_value=0))  # skips the delete
    monkeypatch.setattr("app.services.audit.prune", AsyncMock(return_value=3))
    with caplog.at_level(logging.INFO, logger=scheduler_module.__name__):
        await sched._clean_old_history(force=True)
    assert "Removed 3 audit entries" in caplog.text


async def test_clean_old_history_survives_a_broken_database(monkeypatch, sched):
    @asynccontextmanager
    async def broken():
        raise RuntimeError("disk full")
        yield  # pragma: no cover

    monkeypatch.setattr(scheduler_module, "async_session", broken)
    await sched._clean_old_history(force=True)
    assert sched._last_cleanup_time is not None
