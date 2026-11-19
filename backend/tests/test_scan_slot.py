"""The shared scan slot (app/scanner/scan_slot.py): scheduled scans skip a busy slot, a requested
scan stops a scheduled one and takes over, and two requested scans never run at once."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.api import scanner
from app.scanner import scan_slot as slot_module
from app.scanner import scheduler as scheduler_module
from app.scanner.discovery import ScanCancelled
from app.scanner.scan_slot import REQUESTED, SCHEDULED, ScanSlot
from app.schemas.scan import ScanRequest, ScanStatus


@pytest.fixture(autouse=True)
def fresh_state():
    original = scanner.state
    scanner.state = scanner.ScanStateManager()
    yield
    scanner.state = original


async def test_a_free_slot_is_taken_and_released_only_by_its_holder():
    slot = ScanSlot()
    mine = await slot.try_acquire(SCHEDULED)
    assert mine is not None and slot.kind == SCHEDULED
    await slot.release(asyncio.Event())  # someone else's event: ignored
    assert slot.kind == SCHEDULED
    await slot.release(mine)
    assert slot.kind is None


async def test_a_scheduled_scan_skips_a_busy_slot():
    slot = ScanSlot()
    held = await slot.try_acquire(REQUESTED)
    assert await slot.try_acquire(SCHEDULED) is None
    assert not held.is_set()


async def test_a_requested_scan_never_stops_another_requested_scan():
    slot = ScanSlot()
    held = await slot.try_acquire(REQUESTED)
    assert await slot.try_acquire(REQUESTED) is None
    assert not held.is_set()


async def test_a_requested_scan_stops_the_scheduled_one_and_takes_over():
    slot = ScanSlot()
    scheduled = await slot.try_acquire(SCHEDULED)

    async def scheduled_scan():
        await scheduled.wait()  # runs until it is told to stop
        await slot.release(scheduled)

    running = asyncio.create_task(scheduled_scan())
    requested = await asyncio.wait_for(slot.try_acquire(REQUESTED), timeout=2)
    await running

    assert scheduled.is_set()
    assert requested is not None and requested is not scheduled
    assert slot.kind == REQUESTED


async def test_a_scheduled_scan_that_does_not_stop_in_time_refuses_the_start(monkeypatch):
    monkeypatch.setattr(slot_module, "PREEMPT_WAIT_SECONDS", 0.05)
    slot = ScanSlot()
    scheduled = await slot.try_acquire(SCHEDULED)
    assert await slot.try_acquire(REQUESTED) is None
    assert scheduled.is_set() and slot.kind == SCHEDULED


async def test_cancel_stops_whoever_holds_the_slot():
    slot = ScanSlot()
    assert slot.cancel() is False
    held = await slot.try_acquire(SCHEDULED)
    assert slot.cancel() is True and held.is_set()


# --- the scheduler ---------------------------------------------------------------------------------

async def test_a_scheduled_round_is_skipped_while_another_scan_runs(_fresh_scan_slot):
    await _fresh_scan_slot.try_acquire(REQUESTED)
    scan = AsyncMock()
    await scheduler_module._run_in_scan_slot("Scheduled quick check", scan)
    scan.assert_not_awaited()


async def test_a_scheduled_scan_that_makes_way_ends_quietly_and_frees_the_slot(_fresh_scan_slot):
    async def scan(cancel_event):
        raise ScanCancelled(2)

    await scheduler_module._run_in_scan_slot("Scheduled full scan", scan)
    assert _fresh_scan_slot.kind is None


# --- the API ---------------------------------------------------------------------------------------

async def test_start_scan_stops_a_running_scheduled_scan_and_runs(monkeypatch, _fresh_scan_slot):
    scheduled_stopped = asyncio.Event()

    async def scheduled(cancel_event):
        await cancel_event.wait()
        scheduled_stopped.set()
        raise ScanCancelled()

    background = asyncio.create_task(scheduler_module._run_in_scan_slot("Scheduled quick check", scheduled))
    await asyncio.sleep(0)  # the scheduled scan takes the slot
    assert _fresh_scan_slot.kind == SCHEDULED

    async def fake_planner(subnets, progress_callback, hosts_callback, cancel_event):
        assert _fresh_scan_slot.kind == REQUESTED
        return 4

    monkeypatch.setattr(scanner, "run_planner_scan", fake_planner)
    result = await scanner.start_scan(ScanRequest(subnets=["10.0.0.0/24"]))
    await scanner.state.task
    await background

    assert result["status"] == "ok"
    assert scheduled_stopped.is_set()
    assert scanner.state.last_progress.status == ScanStatus.COMPLETED
    assert _fresh_scan_slot.kind is None


async def test_the_quick_subnet_scan_is_refused_while_a_started_scan_runs(monkeypatch, _fresh_scan_slot):
    planner = AsyncMock(return_value=0)
    monkeypatch.setattr(scanner, "run_planner_scan", planner)
    assert await scanner.state.try_start()

    result = await scanner.quick_subnet_scan("192.168.1.0/24")

    assert result["status"] == "error"
    planner.assert_not_awaited()
    await scanner.state.finish()
    assert _fresh_scan_slot.kind is None


async def test_a_stop_while_the_start_waits_for_the_scheduled_scan_is_kept(_fresh_scan_slot):
    """Stop during the takeover: the started scan must not run as if nothing had been pressed."""
    scheduled = await _fresh_scan_slot.try_acquire(SCHEDULED)

    async def scheduled_scan_makes_way():
        await scheduled.wait()
        await scanner.stop_scan()  # Stop arrives while try_start still waits
        await _fresh_scan_slot.release(scheduled)

    background = asyncio.create_task(scheduled_scan_makes_way())
    assert await scanner.state.try_start() is True
    await background

    assert scanner.state.cancel_event.is_set()
    await scanner.state.finish()
    assert _fresh_scan_slot.kind is None


async def test_a_start_cancelled_while_it_waits_frees_its_reservation(_fresh_scan_slot):
    """The request went away during the takeover: later starts must not be refused for good."""
    await _fresh_scan_slot.try_acquire(SCHEDULED)  # never lets go
    waiting = asyncio.create_task(scanner.state.try_start())
    await asyncio.sleep(0.01)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert await scanner.state.get_active() is False


async def test_stop_also_reaches_a_scheduled_scan(_fresh_scan_slot):
    held = await _fresh_scan_slot.try_acquire(SCHEDULED)
    await scanner.stop_scan()
    assert held.is_set()
