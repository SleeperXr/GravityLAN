"""Edges of webhook delivery: addresses that do not parse, an outbox that cannot be filled."""

import asyncio
import logging
import socket
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.services import webhook_service

_PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


@pytest.fixture(autouse=True)
def _no_proxy_from_the_environment(monkeypatch):
    """Pinning depends on the proxy routing: a proxy set on the developer's machine or the CI runner
    must not change what these tests see. Tests that need one set it themselves."""
    for name in _PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


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
    # Connection: close, so no pooled connection opened for another name on this address carries it
    assert kwargs["headers"] == {"X": "1", "Host": "hooks.example.test:8443", "Connection": "close"}
    # TLS still names (and checks the certificate of) the host, not the address
    assert kwargs["extensions"] == {"sni_hostname": "hooks.example.test"}


async def test_a_name_that_does_not_resolve_is_a_retryable_failure_not_a_post(monkeypatch):
    """Resolution failed: not posted (httpx could resolve to another target), but retried later:
    a DNS server that restarts must not turn the notification into a blocked target."""
    async def fails(host, port, type=0):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fails)
    client = _Recorder()
    with pytest.raises(httpx.ConnectError):
        await webhook_service._send_webhook_post(client, "http://hooks.example.test/x", {})
    assert client.calls == []


async def test_an_unresolvable_target_keeps_the_outbox_entry_pending_for_a_retry(monkeypatch):
    async def fails(host, port, type=0):
        raise socket.gaierror("temporary failure in name resolution")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fails)
    entry = SimpleNamespace(attempts=0, max_attempts=3, status="pending", last_error=None,
                            next_attempt_at=None, event_type="device.offline")
    delivered = await webhook_service._execute_and_record_delivery(_Recorder(), "http://hooks.example.test/x", {}, {}, entry)
    assert delivered is False
    assert entry.status == "pending" and entry.attempts == 1
    assert "could not be resolved" in entry.last_error


def _real_client_recording_posts():
    """An httpx client with the environment's proxy routing, whose posts are only recorded."""
    client = httpx.AsyncClient()
    calls = []

    async def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, text="")

    client.post = post
    return client, calls


async def _resolve_to_public(monkeypatch):
    async def resolves(host, port, type=0):
        return [(2, 1, 6, "", ("198.51.100.7", port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolves)


@pytest.mark.parametrize("no_proxy, pinned", [
    (None, False),                         # through the proxy: the proxy resolves and connects
    ("hooks.example.test", True),          # bypassed by name
    ("localhost,*", True),                 # a "*" inside the list turns proxies off in httpx
    ("hooks.example.test:8443", False),    # another port: still through the proxy
])
async def test_the_pinning_follows_the_clients_own_proxy_routing(monkeypatch, no_proxy, pinned):
    """urllib's NO_PROXY rules differ from httpx's ("*" in a list, ports); only the client decides."""
    await _resolve_to_public(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.lan:3128")
    if no_proxy:
        monkeypatch.setenv("NO_PROXY", no_proxy)
    client, calls = _real_client_recording_posts()
    await webhook_service._send_webhook_post(client, "https://hooks.example.test/x", {})
    url, kwargs = calls[0]
    assert (url == "https://198.51.100.7/x") is pinned
    assert (kwargs["extensions"] == {"sni_hostname": "hooks.example.test"}) is pinned


def test_ipv6_and_international_names_give_valid_host_headers():
    url, headers, ext = webhook_service._pinned_request("http://[fd00::10]:8080/hook", "fd00::10", None)
    assert url == "http://[fd00::10]:8080/hook" and headers["Host"] == "[fd00::10]:8080"
    url, headers, ext = webhook_service._pinned_request("https://büro.example.test/hook", "198.51.100.7", None)
    assert headers["Host"] == "xn--bro-hoa.example.test"
    assert ext == {"sni_hostname": "xn--bro-hoa.example.test"}


async def test_the_name_is_encoded_as_httpx_does_for_dns_host_and_sni(monkeypatch):
    """Python's "idna" codec (IDNA 2003) maps faß to fass, another domain; httpx uses IDNA 2008."""
    looked_up = []

    async def resolves(host, port, type=0):
        looked_up.append(host)
        return [(2, 1, 6, "", ("198.51.100.7", port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolves)
    client = _Recorder()
    await webhook_service._send_webhook_post(client, "https://faß.example.test/hook", {})
    assert looked_up == ["xn--fa-hia.example.test"]
    url, kwargs = client.calls[0]
    assert kwargs["headers"]["Host"] == "xn--fa-hia.example.test"
    assert kwargs["extensions"] == {"sni_hostname": "xn--fa-hia.example.test"}


async def test_a_failure_while_queueing_is_logged_and_not_raised(caplog):
    with patch.object(webhook_service, "async_session", side_effect=RuntimeError("database gone")), \
            caplog.at_level(logging.ERROR, logger=webhook_service.logger.name):
        await webhook_service._enqueue_and_dispatch("device.offline", {"ip": "192.0.2.1"})
    assert "Failed to enqueue outbox notifications for device.offline" in caplog.text
