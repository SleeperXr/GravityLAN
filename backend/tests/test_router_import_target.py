"""The router import's target checks (app/services/router_import/base.py) for names that resolve badly."""

import asyncio
import ipaddress
import socket

import pytest

from app.services.router_import.base import RouterImportError, RouterProvider, is_lan_address, resolve_lan_target


def _resolver(monkeypatch, answer):
    async def fake_getaddrinfo(host, port, type=0):
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [socket.gaierror("no such host"), UnicodeError("label too long")])
async def test_a_name_that_does_not_resolve(monkeypatch, error):
    _resolver(monkeypatch, error)
    with pytest.raises(RouterImportError, match="could not be resolved") as err:
        await resolve_lan_target("router.lan")
    assert err.value.status_code == 400


@pytest.mark.asyncio
async def test_a_name_with_only_unreadable_addresses(monkeypatch):
    _resolver(monkeypatch, [(2, 1, 6, "", ("not-an-ip", 0))])
    with pytest.raises(RouterImportError, match="could not be resolved"):
        await resolve_lan_target("router.lan")


@pytest.mark.asyncio
async def test_unreadable_addresses_are_skipped_and_ipv4_preferred(monkeypatch):
    _resolver(monkeypatch, [
        (10, 1, 6, "", ("fd00::1%eth0", 0, 0, 2)),  # a scope id is cut off
        (2, 1, 6, "", ("garbage", 0)),
        (2, 1, 6, "", ("192.168.7.1", 0)),
    ])
    assert await resolve_lan_target("router.lan") == "192.168.7.1"


def test_ipv4_mapped_addresses_are_judged_as_ipv4():
    assert is_lan_address(ipaddress.ip_address("::ffff:192.168.1.1")) is True
    assert is_lan_address(ipaddress.ip_address("::ffff:127.0.0.1")) is False


@pytest.mark.asyncio
async def test_the_base_provider_has_no_fetch():
    with pytest.raises(NotImplementedError):
        await RouterProvider().fetch(None)
