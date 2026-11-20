"""Authoritative transport-peer proxy trust resolution and outermost ASGI proxy middleware.

Uvicorn must be started with ``--no-proxy-headers`` / ``proxy_headers=False`` so its built-in
``ProxyHeadersMiddleware`` does not overwrite ``scope["client"]`` before the application sees the
true TCP transport peer. ``TrustedProxyMiddleware`` runs as the outermost ASGI middleware on
``http`` and ``websocket`` scopes (passing ``lifespan`` through untouched), records the original
peer and whether that peer is trusted on ``scope["state"]``, and then delegates to Uvicorn's
``ProxyHeadersMiddleware`` to rewrite ``client`` and ``scheme`` from trusted proxy headers.
"""

from __future__ import annotations

import ipaddress
import os
from functools import lru_cache

from uvicorn._types import ASGI3Application, ASGIReceiveCallable, ASGISendCallable, Scope
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings

DEFAULT_TRUSTED_PROXIES = "127.0.0.1,::1"
STATE_TRANSPORT_PEER = "gl_transport_peer"
STATE_FROM_TRUSTED_PROXY = "gl_from_trusted_proxy"

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def effective_trusted_proxies_raw() -> str:
    """Resolve effective proxy trust config: GRAVITYLAN_TRUSTED_PROXIES -> FORWARDED_ALLOW_IPS -> default."""
    configured = (settings.trusted_proxies or "").strip()
    if configured:
        return configured
    if "FORWARDED_ALLOW_IPS" in os.environ:
        return os.environ["FORWARDED_ALLOW_IPS"]
    return DEFAULT_TRUSTED_PROXIES


@lru_cache(maxsize=64)
def parse_trusted_proxy_networks(raw: str) -> tuple[IPNetwork, ...] | None:
    """Parse comma-separated IPs/CIDRs into network objects; ``None`` means explicit ``*`` trust.

    Invalid entries (hostnames, typos) are ignored and never widen trust; an empty or
    all-invalid string returns an empty tuple, trusting no peer.
    """
    networks: list[IPNetwork] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if entry == "*":
            return None
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def is_trusted_proxy_peer(
    peer_host: str | None,
    networks: tuple[IPNetwork, ...] | None,
) -> bool:
    """True when ``peer_host`` is directly covered by ``networks`` (or ``networks is None`` for ``*``)."""
    if networks is None:
        return True
    if not peer_host:
        return False
    try:
        address = ipaddress.ip_address(peer_host)
    except ValueError:
        return False
    return any(address in net for net in networks)


class TrustedProxyMiddleware:
    """Outermost ASGI middleware recording original peer trust before Uvicorn rewrites client/scheme."""

    def __init__(self, app: ASGI3Application) -> None:
        self.app = app
        self._proxy_mw_cache: dict[str, tuple[tuple[IPNetwork, ...] | None, ProxyHeadersMiddleware]] = {}

    def _get_proxy_handler(self, raw: str) -> tuple[tuple[IPNetwork, ...] | None, ProxyHeadersMiddleware]:
        cached = self._proxy_mw_cache.get(raw)
        if cached is not None:
            return cached
        networks = parse_trusted_proxy_networks(raw)
        trusted_arg: str | list[str] = "*" if networks is None else [str(net) for net in networks]
        proxy_mw = ProxyHeadersMiddleware(self.app, trusted_hosts=trusted_arg)
        if len(self._proxy_mw_cache) >= 32:
            self._proxy_mw_cache.clear()
        self._proxy_mw_cache[raw] = (networks, proxy_mw)
        return networks, proxy_mw

    async def __call__(self, scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        client_addr = scope.get("client")
        peer_host = client_addr[0] if client_addr else None
        raw = effective_trusted_proxies_raw()
        networks, proxy_mw = self._get_proxy_handler(raw)
        from_trusted = is_trusted_proxy_peer(peer_host, networks)

        state = scope.setdefault("state", {})
        state[STATE_TRANSPORT_PEER] = peer_host
        state[STATE_FROM_TRUSTED_PROXY] = from_trusted

        await proxy_mw(scope, receive, send)
