import asyncio
import logging
import socket
import sys
import subprocess

try:
    import dns.exception  # type: ignore
    import dns.resolver # type: ignore
    import dns.reversename  # noqa: F401 — availability probe used inside resolve_hostname
    HAS_DNS_PYTHON = True
except ImportError:
    HAS_DNS_PYTHON = False

logger = logging.getLogger(__name__)

import re
from datetime import datetime, timezone
from typing import Optional

IP_PATTERN = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

def is_ip_like(name: Optional[str]) -> bool:
    """Checks if a name looks like an IP address or is a generic placeholder."""
    if not name:
        return True
    return bool(IP_PATTERN.match(name)) or name.lower() in ["unbekannt", "unknown"]

def mask_ip(ip: Optional[str]) -> str:
    """Masks the host portion of an IP address (e.g. 192.168.1.1 -> 192.168.x.x) for secure logging."""
    if not ip:
        return ""
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.x.x"
    return "x.x.x.x"

# Simple in-memory cache for DNS resolutions
# Format: {ip: (hostname, timestamp)}
_dns_cache: dict[str, tuple[Optional[str], datetime]] = {}
DNS_CACHE_TTL = 3600  # 1 hour for a found name
# A miss is remembered for less than the 5-minute quick scan, so every quick scan retries the
# names of "Unknown" devices (a TV that was asleep, a phone that just joined) instead of hourly.
DNS_NEGATIVE_CACHE_TTL = 240

def _resolve_win32(ip: str) -> Optional[str]:
    """Try Win32 GetNameInfoW for fast local resolution."""
    if sys.platform != 'win32': return None
    try:
        import ctypes
        ws2_32 = ctypes.windll.ws2_32
        
        class sockaddr_in(ctypes.Structure):
            _fields_ = [
                ("sin_family", ctypes.c_short),
                ("sin_port", ctypes.c_ushort),
                ("sin_addr", ctypes.c_ubyte * 4),
                ("sin_zero", ctypes.c_char * 8),
            ]
        
        sa = sockaddr_in()
        sa.sin_family = 2 # AF_INET
        ip_parts = [int(p) for p in ip.split('.')]
        for i, part in enumerate(ip_parts):
            sa.sin_addr[i] = part
        
        host = ctypes.create_unicode_buffer(1024)
        res = ws2_32.GetNameInfoW(
            ctypes.byref(sa), ctypes.sizeof(sa),
            host, ctypes.sizeof(host),
            None, 0,
            0x08 # NI_NAMEREQD
        )
        if res == 0 and host.value:
            return host.value
    except Exception:
        pass
    return None

def _try_avahi(ip: str) -> Optional[str]:
    """Try avahi-resolve (mDNS) for reverse resolution."""
    try:
        res = subprocess.run(["avahi-resolve", "-a", ip], capture_output=True, text=True, timeout=1.0)
        if res.returncode == 0 and res.stdout:
            parts = res.stdout.strip().split()
            if len(parts) >= 2:
                return parts[1]
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def _try_dig(ip: str, dns_server: str | None = None) -> Optional[str]:
    """Try dig +short -x (Reverse DNS), asking the configured DNS server if there is one."""
    cmd = ["dig", "+short", "-x", ip]
    if dns_server:
        cmd.insert(1, f"@{dns_server}")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1.0)
        if res.returncode == 0 and res.stdout:
            name = res.stdout.strip().rstrip('.')
            if name:
                return name
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def _resolve_linux_shell(ip: str, dns_server: str | None = None) -> Optional[str]:
    """Try Linux shell tools for reverse resolution (avahi, dig).

    No "nmap -sn" fallback any more: discovery already ran it for the subnet, and a
    3 s nmap per host without a DNS name slowed every scan down.
    """
    return _try_avahi(ip) or _try_dig(ip, dns_server)


def _parse_ping_hostname(stdout: str, ip: str) -> Optional[str]:
    """Extract a hostname from 'ping -a' output lines like 'Pinging host [ip] ...'."""
    for line in stdout.splitlines():
        if "ping" in line.lower() and "[" in line:
            name = line.split("[")[0].strip().split()[-1]
            if name and name != ip:
                return name
    return None


def _resolve_ping_win32(ip: str) -> Optional[str]:
    """Try Windows 'ping -a' for reverse resolution."""
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run(
            ["ping", "-a", "-n", "1", "-w", "200", ip],
            capture_output=True, text=True, encoding="cp850",
            startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=2.0
        )
        return _parse_ping_hostname(res.stdout, ip)
    except (subprocess.SubprocessError, OSError):
        return None


def _resolve_shell(ip: str, dns_server: str | None = None) -> Optional[str]:
    """Try OS-specific shell commands (ping -a, avahi, dig)."""
    if sys.platform == 'win32':
        return _resolve_ping_win32(ip)
    return _resolve_linux_shell(ip, dns_server)

async def resolve_hostname(ip: str, timeout: float = 3.0, dns_server: str | None = None, use_cache: bool = True) -> str | None:
    """Resolve an IP address to its hostname via reverse DNS (FQDN).

    ``use_cache=False`` is for a refresh the user asked for: it always looks again.
    """
    from datetime import datetime

    # 0. Check Cache
    now = datetime.now(timezone.utc)
    if use_cache and ip in _dns_cache:
        cached_name, cached_time = _dns_cache[ip]
        ttl = DNS_CACHE_TTL if cached_name else DNS_NEGATIVE_CACHE_TTL
        if (now - cached_time).total_seconds() < ttl:
            return cached_name

    loop = asyncio.get_running_loop()

    def _resolve() -> str | None:
        # 1. Try Win32 API
        win32_name = _resolve_win32(ip)
        if win32_name: return win32_name

        # 2. Try uncached direct DNS query (bypasses OS cache)
        if HAS_DNS_PYTHON:
            try:
                import dns.resolver # type: ignore
                import dns.reversename  # noqa: F401 — availability probe used inside resolve_hostname
                resolver = dns.resolver.Resolver()
                
                if dns_server:
                    resolver.nameservers = [dns_server]
                
                rev_name = dns.reversename.from_address(ip)
                resolver.lifetime = timeout - 0.5
                resolver.timeout = timeout - 0.5
                answers = resolver.resolve(rev_name, "PTR")
                if answers:
                    resolved_name = str(answers[0]).rstrip('.')
                    logger.info("Custom DNS resolved host to: %s", resolved_name)
                    return resolved_name
            except Exception as e:
                logger.debug("Direct DNS PTR query failed: %s", e)

        # 3. Fallback to OS resolver (socket)
        try:
            name, _ = socket.getnameinfo((ip, 0), 0)
            if name and name != ip:
                return name
        except Exception:
            pass

        # 4. Try Shell Commands (ping -a, avahi, dig)
        shell_name = _resolve_shell(ip, dns_server)
        if shell_name: return shell_name

        return None

    try:
        resolved_name = await asyncio.wait_for(loop.run_in_executor(None, _resolve), timeout=timeout + 1.0)
        # Update Cache
        _dns_cache[ip] = (resolved_name, datetime.now(timezone.utc))
        return resolved_name
    except asyncio.TimeoutError:
        logger.debug("DNS resolution timeout")
        _dns_cache[ip] = (None, datetime.now(timezone.utc)) # Cache failure too
        return None
    except Exception as e:
        logger.debug("DNS resolution error: %s", e)
        _dns_cache[ip] = (None, datetime.now(timezone.utc))
        return None

HOSTNAME_SOURCES = ("dns1", "dns2")


def _ptr_failure(error: Exception) -> str:
    """Why a PTR query found no name, in the words the editor shows."""
    if isinstance(error, (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer)):
        return "no_entry"  # the server answered: it has no name for this IP
    if isinstance(error, dns.exception.Timeout):
        return "timeout"  # nothing answered in time: no DNS there, or blocked
    if isinstance(error, dns.resolver.NoNameservers):
        # Each entry is (server, tcp, port, error, response); the error is the rcode's text when one answered
        codes = [entry[3] for entry in error.kwargs.get("errors") or [] if len(entry) > 3]
        if "REFUSED" in codes:
            return "refused"
        return "server_error" if any(isinstance(code, str) for code in codes) else "error"
    return "error"


def ptr_lookup(ip: str, dns_server: str | None, timeout: float = 2.0) -> tuple[str | None, str | None]:
    """The PTR name one DNS server gives for an IP (None: the system's servers) and, without one, why not."""
    if not HAS_DNS_PYTHON:
        return None, "error"
    try:
        resolver = dns.resolver.Resolver()
        if dns_server:
            resolver.nameservers = [dns_server]
        resolver.timeout = resolver.lifetime = timeout
        answers = resolver.resolve(dns.reversename.from_address(ip), "PTR")
        name = str(answers[0]).rstrip(".") if answers else ""
        return (name, None) if name else (None, "no_entry")
    except Exception as e:
        logger.info("PTR query for %s at %s found no name: %s", mask_ip(ip), dns_server or "system DNS", e)
        return None, _ptr_failure(e)


def query_ptr(ip: str, dns_server: str | None, timeout: float = 2.0) -> str | None:
    """The PTR name one DNS server gives for an IP, or None."""
    return ptr_lookup(ip, dns_server, timeout)[0]


async def lookup_dns_names(ip: str, primary: str | None, secondary: str | None) -> dict[str, str | None]:
    """What DNS 1 and DNS 2 each call an IP, asked side by side: {"1": name, "2": name}, plus
    "<n>_reason" for a server that gave no name (see `_ptr_failure`)."""
    loop = asyncio.get_running_loop()
    results = await asyncio.gather(
        loop.run_in_executor(None, ptr_lookup, ip, primary),
        loop.run_in_executor(None, ptr_lookup, ip, secondary),
    )
    names: dict[str, str | None] = {}
    for n, (name, reason) in zip(("1", "2"), results):
        names[n] = name
        if reason:
            names[f"{n}_reason"] = reason
    return names


def choose_hostname(found: str | None, names: dict[str, str | None] | None, source: str | None) -> str | None:
    """The hostname a device gets: the DNS server the user picked when it answered, else the usual lookup
    (`found`), else DNS 2's answer, else DNS 1's."""
    names = names or {}
    if source in HOSTNAME_SOURCES and names.get(source[-1]):
        return names[source[-1]]
    return found or names.get("2") or names.get("1")


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
                logger.info("Resolved device to %s", hostname)
        return host

    tasks = [_resolve_single(h) for h in hosts]
    await asyncio.gather(*tasks, return_exceptions=True)
    return hosts
