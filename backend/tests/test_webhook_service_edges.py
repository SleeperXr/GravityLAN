"""Edges of webhook delivery: addresses that do not parse, an outbox that cannot be filled."""

import asyncio
import logging
from unittest.mock import patch

from app.services import webhook_service


async def test_a_resolved_address_that_does_not_parse_is_skipped(monkeypatch):
    async def resolves(host, port, type=0):
        return [(2, 1, 6, "", ("not-an-address", port)), (2, 1, 6, "", ("198.51.100.7", port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolves)
    assert await webhook_service._blocked_target_reason("http://hooks.example.test/x") is None


async def test_a_blocked_address_behind_one_that_does_not_parse_is_still_found(monkeypatch):
    async def resolves(host, port, type=0):
        return [(2, 1, 6, "", ("not-an-address", port)), (2, 1, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolves)
    assert "127.0.0.1" in await webhook_service._blocked_target_reason("http://hooks.example.test/x")


async def test_a_failure_while_queueing_is_logged_and_not_raised(caplog):
    with patch.object(webhook_service, "async_session", side_effect=RuntimeError("database gone")), \
            caplog.at_level(logging.ERROR, logger=webhook_service.logger.name):
        await webhook_service._enqueue_and_dispatch("device.offline", {"ip": "192.0.2.1"})
    assert "Failed to enqueue outbox notifications for device.offline" in caplog.text
