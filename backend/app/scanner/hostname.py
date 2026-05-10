import asyncio
import logging
import socket
import sys
import subprocess
import concurrent.futures

try:
    import dns.resolver # type: ignore
    import dns.reversename # type: ignore
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
    except: pass
    return None

def _resolve_shell(ip: str) -> Optional[str]:
    """Try OS-specific shell commands (ping -a, avahi, dig)."""
    if sys.platform == 'win32':
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            res = subprocess.run(
                ["ping", "-a", "-n", "1", "-w", "200", ip],
                capture_output=True, text=True, encoding="cp850",
                startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=2.0
            )
            for line in res.stdout.splitlines():
                if "ping" in line.lower() and "[" in line:
                    name = line.split("[")[0].strip().split()[-1]
                    if name and name != ip:
                        return name
        except: pass
    else:
        # Try avahi-resolve (mDNS)
        try:
            res = subprocess.run(["avahi-resolve", "-a", ip], capture_output=True, text=True, timeout=1.0)
            if res.returncode == 0 and res.stdout:
                parts = res.stdout.strip().split()
                if len(parts) >= 2: return parts[1]
        except: pass
        
        # Try dig (Reverse DNS)
        try:
            res = subprocess.run(["dig", "+short", "-x", ip], capture_output=True, text=True, timeout=1.0)
            if res.returncode == 0 and res.stdout:
                name = res.stdout.strip().rstrip('.')
                if name: return name
        except: pass

        # Try nmap resolution (Final powerful fallback)
        try:
            res = subprocess.run(["nmap", "-sn", ip], capture_output=True, text=True, timeout=3.0)
            if res.returncode == 0:
                # Look for "Nmap scan report for <hostname> (<ip>)"
                match = re.search(r"Nmap scan report for (.*) \(" + re.escape(ip) + r"\)", res.stdout)
                if match:
                    name = match.group(1).strip()
                    if name and not is_ip_like(name):
                        return name
        except: pass
    return None

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
        # 1. Try Win32 API
        win32_name = _resolve_win32(ip)
        if win32_name: return win32_name

        # 2. Try uncached direct DNS query (bypasses OS cache)
        if HAS_DNS_PYTHON:
            try:
                import dns.resolver # type: ignore
                import dns.reversename # type: ignore
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

        # 3. Fallback to OS resolver (socket)
        try:
            name, _ = socket.getnameinfo((ip, 0), 0)
            if name and name != ip:
                return name
        except Exception:
            pass

        # 4. Try Shell Commands (ping -a, avahi, dig)
        shell_name = _resolve_shell(ip)
        if shell_name: return shell_name

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
