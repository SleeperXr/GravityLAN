"""Warn once when a request carries X-Forwarded-For from an address that is not a trusted proxy.

TrustedProxyMiddleware checks the original TCP transport peer against GRAVITYLAN_TRUSTED_PROXIES
(or FORWARDED_ALLOW_IPS, defaulting to 127.0.0.1,::1) before rewriting client/scheme. When a
request arrives with X-Forwarded-For from an untrusted peer, the header is ignored, and GravityLAN
logs a single warning naming the original transport peer.
"""
import logging

from app.services.proxy_trust import (
    effective_trusted_proxies_raw,
    is_trusted_proxy_peer,
    parse_trusted_proxy_networks,
)

logger = logging.getLogger(__name__)

_warned = False


def forwarded_by_untrusted(
    client_host: str | None,
    forwarded_for: str | None,
    *,
    from_trusted_proxy: bool | None = None,
) -> bool:
    """True when X-Forwarded-For is set and the transport peer is not a trusted proxy."""
    if not client_host or not forwarded_for or not forwarded_for.strip():
        return False
    if from_trusted_proxy is not None:
        return not from_trusted_proxy
    networks = parse_trusted_proxy_networks(effective_trusted_proxies_raw())
    return not is_trusted_proxy_peer(client_host, networks)


def check_forwarded_for(
    client_host: str | None,
    forwarded_for: str | None,
    *,
    from_trusted_proxy: bool | None = None,
) -> None:
    """Log one warning per process for the first request forwarded by an untrusted peer."""
    global _warned
    if _warned or not forwarded_by_untrusted(client_host, forwarded_for, from_trusted_proxy=from_trusted_proxy):
        return
    _warned = True
    logger.warning(
        "A request from %s carries X-Forwarded-For, but %s is not a trusted proxy, so the header is "
        "ignored and the login limit, the audit log and agent IPs see %s instead of the real client. "
        "If this is your reverse proxy, add its address or network to GRAVITYLAN_TRUSTED_PROXIES "
        "(for example GRAVITYLAN_TRUSTED_PROXIES=%s). This warning is shown once per start.",
        client_host, client_host, client_host, client_host)
