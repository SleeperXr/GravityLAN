import asyncio
import logging
import socket
import concurrent.futures

try:
    import dns.resolver
    import dns.reversename
    HAS_DNS_PYTHON = True
except ImportError:
    HAS_DNS_PYTHON = False

logger = logging.getLogger(__name__)

import re
from datetime import datetime
from typing import Optional

IP_PATTERN = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

def is_ip_like(name: Optional[str]) -> bool:
    """Checks if a name looks like an IP address or is a generic placeholder."""
    if not name:
        return True
    return bool(IP_PATTERN.match(name)) or name.lower() in ["unbekannt", "unknown"]

# Simple in-memory cache for DNS resolutions
# Format: {ip: (hostname, timestamp)}
_dns_cache: dict[str, tuple[Optional[str], datetime]] = {}
DNS_CACHE_TTL = 3600  # 1 hour

async def resolve_hostname(ip: str, timeout: float = 3.0, dns_server: str | None = None) -> str | None:
    """Resolve an IP address to its hostname via reverse DNS (FQDN)."""
    from datetime import datetime
    
    # 0. Check Cache
    now = datetime.now()
    if ip in _dns_cache:
        cached_name, cached_time = _dns_cache[ip]
        if (now - cached_time).total_seconds() < DNS_CACHE_TTL:
            return cached_name

    loop = asyncio.get_running_loop()

    def _resolve() -> str | None:
        # 1. Try uncached direct DNS query (bypasses OS cache)
        if HAS_DNS_PYTHON:
            try:
                import dns.resolver
                import dns.reversename
                resolver = dns.resolver.Resolver()
                
                if dns_server:
                    resolver.nameservers = [dns_server]
                
                rev_name = dns.reversename.from_address(ip)
                resolver.lifetime = timeout - 0.5
                resolver.timeout = timeout - 0.5
                answers = resolver.resolve(rev_name, "PTR")
                if answers:
                    resolved_name = str(answers[0]).rstrip('.')
                    logger.info(f"Custom DNS resolved {ip} to: {resolved_name}")
                    return resolved_name
            except Exception as e:
                logger.debug(f"Direct DNS PTR query for {ip} failed: {e}")

        # 2. Fallback to OS resolver (socket)
        try:
            name, _ = socket.getnameinfo((ip, 0), 0)
            if name and name != ip:
                return name
        except Exception:
            pass

        return None

    try:
        resolved_name = await asyncio.wait_for(loop.run_in_executor(None, _resolve), timeout=timeout + 1.0)
        # Update Cache
        _dns_cache[ip] = (resolved_name, datetime.now())
        return resolved_name
    except asyncio.TimeoutError:
        logger.debug(f"DNS resolution timeout for {ip}")
        _dns_cache[ip] = (None, datetime.now()) # Cache failure too
        return None
    except Exception as e:
        logger.debug(f"DNS resolution error for {ip}: {e}")
        _dns_cache[ip] = (None, datetime.now())
        return None

async def resolve_hostnames(
    hosts: list[dict],
    timeout: float = 3.5,
    max_concurrent: int = 5,
    dns_server: str | None = None,
    cancel_event: asyncio.Event | None = None,
) -> list[dict]:
    """Resolve hostnames for multiple hosts concurrently."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _resolve_single(host: dict) -> dict:
        if cancel_event and cancel_event.is_set():
            return host
            
        async with semaphore:
            if cancel_event and cancel_event.is_set():
                return host
            hostname = await resolve_hostname(host["ip"], timeout, dns_server)
            # Only update if we actually found something
            if hostname:
                host["hostname"] = hostname
                logger.info(f"Resolved {host['ip']} to {hostname}")
        return host

    tasks = [_resolve_single(h) for h in hosts]
    await asyncio.gather(*tasks, return_exceptions=True)
    return hosts
