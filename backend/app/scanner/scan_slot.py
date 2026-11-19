"""One active network scan at a time, shared by the manual scans and the scheduler.

A planner or dashboard scan sweeps subnets with nmap and writes what it finds; two at once
compete for the database and judge the same devices twice. Every such scan takes the slot:

- Scheduled scans (the full scan and the quick check) take it only when it is free and
  otherwise skip their round; the next round comes soon enough.
- A scan someone started (Start scan, the quick subnet scan of the Network page) has priority:
  it stops a scheduled scan that holds the slot, waits until that one has let go, and runs.
  It never stops another scan someone started; that start is refused instead.

The holder gets a cancel event for the scan functions; ``cancel()`` (the Stop button) sets it.
The passive ARP loop, the Docker sync and the health probe do not sweep subnets and need no slot.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

SCHEDULED = "scheduled"
REQUESTED = "requested"

# How long a requested scan waits for a stopped scheduled scan to let go
PREEMPT_WAIT_SECONDS = 15.0


class ScanSlot:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._kind: str | None = None
        self._cancel: asyncio.Event | None = None
        self._released = asyncio.Event()
        self._released.set()

    @property
    def kind(self) -> str | None:
        """Who holds the slot: SCHEDULED, REQUESTED or None."""
        return self._kind

    def _take(self, kind: str) -> asyncio.Event:
        self._kind = kind
        self._cancel = asyncio.Event()
        self._released.clear()
        return self._cancel

    async def try_acquire(self, kind: str) -> asyncio.Event | None:
        """Take the slot; the scan's cancel event, or None when it is taken and stays taken.

        A REQUESTED scan stops a SCHEDULED holder and waits for it (up to PREEMPT_WAIT_SECONDS).
        """
        async with self._lock:
            if self._kind is None:
                return self._take(kind)
            if kind != REQUESTED or self._kind != SCHEDULED:
                return None
            logger.info("Scan slot: stopping the scheduled scan for a requested one")
            self._cancel.set()
            released = self._released
        try:
            await asyncio.wait_for(released.wait(), timeout=PREEMPT_WAIT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("Scan slot: the scheduled scan did not stop within %ss", PREEMPT_WAIT_SECONDS)
            return None
        async with self._lock:
            # Someone else may have come in between; only a free slot is taken
            return self._take(kind) if self._kind is None else None

    async def release(self, cancel_event: asyncio.Event) -> None:
        """Let go of the slot; only the holder (identified by its cancel event) can."""
        async with self._lock:
            if self._cancel is not cancel_event:
                return
            self._kind = None
            self._cancel = None
            self._released.set()

    def cancel(self) -> bool:
        """Stop the scan that holds the slot; False when none does."""
        if self._cancel is None:
            return False
        self._cancel.set()
        return True


scan_slot = ScanSlot()
