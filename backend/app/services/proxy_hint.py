"""Warn once when a request carries X-Forwarded-For from an address that is not a trusted proxy.

uvicorn (--proxy-headers) only takes the client address from X-Forwarded-For when the request
comes from an address in FORWARDED_ALLOW_IPS, which the container fills from
GRAVITYLAN_TRUSTED_PROXIES. Otherwise the header is ignored without a word, and the login limit,
the audit log and agent IPs all see the proxy instead of the real client.

When uvicorn trusted the sender it replaced the client address with an entry of the header, so a
client address that appears nowhere in X-Forwarded-For means the header came from an untrusted
address.
"""
import logging

logger = logging.getLogger(__name__)

_warned = False


def _host(entry: str) -> str:
    """The address of one X-Forwarded-For entry, without a port or IPv6 brackets."""
    entry = entry.strip()
    if entry.startswith("["):
        return entry[1:].split("]", 1)[0]
    if entry.count(":") == 1:  # IPv4 with a port; a bare IPv6 address has several colons
        return entry.split(":", 1)[0]
    return entry


def forwarded_by_untrusted(client_host: str | None, forwarded_for: str | None) -> bool:
    """True when X-Forwarded-For is set but uvicorn did not take the client address from it."""
    if not client_host or not forwarded_for or not forwarded_for.strip():
        return False
    return client_host not in {_host(e) for e in forwarded_for.split(",")}


def check_forwarded_for(client_host: str | None, forwarded_for: str | None) -> None:
    """Log one warning per process for the first request forwarded by an untrusted address."""
    global _warned
    if _warned or not forwarded_by_untrusted(client_host, forwarded_for):
        return
    _warned = True
    logger.warning(
        "A request from %s carries X-Forwarded-For, but %s is not a trusted proxy, so the header is "
        "ignored and the login limit, the audit log and agent IPs see %s instead of the real client. "
        "If this is your reverse proxy, add its address or network to GRAVITYLAN_TRUSTED_PROXIES "
        "(for example GRAVITYLAN_TRUSTED_PROXIES=%s). This warning is shown once per start.",
        client_host, client_host, client_host, client_host)
