"""Close WebSocket streams whose access was revoked (#47, #48).

The log, scan progress and agent metric streams authenticate once, when they open,
and then keep receiving data. Logging out sessions or deleting tokens does not reach
an open stream, so the database reset closes all of them, and a backup import closes
the metric streams of device ids that now name another device.
"""

import asyncio
import logging
from collections.abc import Iterable

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Same code the WebSocket authentication uses when it refuses a connection
REVOKED_CLOSE_CODE = 4003
# A client that does not take the close frame in time is dropped from the registry anyway
CLOSE_TIMEOUT_SECONDS = 2.0


async def _close_one(ws: WebSocket) -> bool:
    try:
        await asyncio.wait_for(ws.close(code=REVOKED_CLOSE_CODE, reason="Access revoked"), CLOSE_TIMEOUT_SECONDS)
        return True
    except Exception as e:
        logger.debug("Revoked WebSocket was already closed or did not answer: %s", e)
        return False


async def _close(sockets: Iterable[WebSocket]) -> int:
    """Close all sockets at once, so a stalled client cannot hold up the request. Returns how many closed."""
    results = await asyncio.gather(*(_close_one(ws) for ws in sockets))
    return sum(results)


async def close_metric_streams(device_ids: Iterable[int]) -> int:
    """Close the dashboard metric streams of ``device_ids``."""
    from app.services.agent_telemetry import _ws_subscribers

    sockets = [ws for device_id in set(device_ids) for ws in _ws_subscribers.pop(device_id, set())]
    return await _close(sockets)


async def close_all_streams() -> int:
    """Close every log, scan progress and metric stream."""
    from app.api.scanner import state as scan_state
    from app.services.agent_telemetry import _ws_subscribers
    from app.services.log_streamer import log_handler

    sockets = [ws for subscribers in _ws_subscribers.values() for ws in subscribers]
    _ws_subscribers.clear()
    sockets += log_handler.detach_all()
    sockets += await scan_state.detach_all_clients()
    return await _close(sockets)
