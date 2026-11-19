"""Edges of webhook delivery: addresses that do not parse, an outbox that cannot be filled."""

import asyncio
import logging
import socket
from types import SimpleNamespace
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


class _Recorder:
    def __init__(self):
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, text="")


async def test_the_post_goes_to_the_checked_address_not_a_second_lookup(monkeypatch):
    """DNS rebinding: the first answer passes the check, a second one would name 127.0.0.1."""
    answers = iter(["198.51.100.7", "127.0.0.1"])

    async def resolves(host, port, type=0):
        return [(2, 1, 6, "", (next(answers), port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolves)
    client = _Recorder()
    await webhook_service._send_webhook_post(client, "https://hooks.example.test:8443/x?y=1", {"a": 1}, headers={"X": "1"})

    url, kwargs = client.calls[0]
    assert url == "https://198.51.100.7:8443/x?y=1"
    assert kwargs["headers"] == {"X": "1", "Host": "hooks.example.test:8443"}
    # TLS still names (and checks the certificate of) the host, not the address
    assert kwargs["extensions"] == {"sni_hostname": "hooks.example.test"}


async def test_a_name_that_does_not_resolve_is_not_posted_to(monkeypatch):
    """Resolution failed: letting httpx look it up again could reach another target."""
    async def fails(host, port, type=0):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fails)
    client = _Recorder()
    assert await webhook_service._send_webhook_post(client, "http://hooks.example.test/x", {}) is None
    assert client.calls == []


async def test_a_failure_while_queueing_is_logged_and_not_raised(caplog):
    with patch.object(webhook_service, "async_session", side_effect=RuntimeError("database gone")), \
            caplog.at_level(logging.ERROR, logger=webhook_service.logger.name):
        await webhook_service._enqueue_and_dispatch("device.offline", {"ip": "192.0.2.1"})
    assert "Failed to enqueue outbox notifications for device.offline" in caplog.text
