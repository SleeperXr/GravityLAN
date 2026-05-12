"""
Host discovery module for GravityLAN.
Provides high-speed Nmap-based scanning with reliable ARP/Ping fallbacks.
"""

import asyncio
import ipaddress
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Set

# Local imports
from app.scanner.hostname import resolve_hostname
from app.scanner.vendor import get_vendor
from app.scanner.utils import check_port_async, ping_host_async
from app.scanner.arp import resolve_mac_addresses, trigger_arp_probe
from app.exceptions import NetworkDiscoveryError

# Standard Logger setup
logger = logging.getLogger(__name__)

# Common ports to check if a host is alive when ping fails
ALIVE_CHECK_PORTS = [445, 135, 80, 22, 443, 8080, 8443, 1883, 8123, 5000, 8266, 9090]

async def discover_hosts_simple(
    target_ips: List[str],
    timeout: float = 1.0,
    max_workers: int = 30,
    cancel_event: Optional[asyncio.Event] = None,
    mode: str = "gentle",
    dns_server: Optional[str] = None,
    host_found_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
) -> List[Dict[str, Any]]:
    """
    Highly accurate host discovery using Nmap (Fast) + Manual ARP/Ping fallback.
    
    Args:
        target_ips: List of IP strings to scan.
        timeout: Timeout per host for alive checks.
        max_workers: Maximum parallel workers for fallback scan.
        cancel_event: Event to trigger scan cancellation.
        mode: Scanning intensity mode.
        dns_server: Optional custom DNS server for Nmap.
        host_found_callback: Async callback triggered for each found host.
        
    Returns:
        A list of dictionaries containing found host data (ip, mac, hostname).
    """
    discovered: List[Dict[str, Any]] = []
    
    # -- 1. Nmap Discovery (Primary) ------------------------------------------
    try:
        networks: Set[str] = set()
        for ip in target_ips:
            try:
                # Group IPs by /24 for Nmap efficiency
                net = ipaddress.IPv4Interface(f"{ip}/24").network
                networks.add(str(net))
            except ValueError:
                logger.warning(f"Invalid IP encountered during discovery: {ip}")
        
        for network in networks:
            if cancel_event and cancel_event.is_set():
                break
            
            if network.startswith("169.254."):  # Skip link-local
                continue

            # Optimization: If target_ips is small, scan IPs directly instead of subnet
            cmd_args = ["nmap", "-sn"]
            if dns_server:
                cmd_args.extend(["--dns-servers", dns_server])
            if len(target_ips) < 50:
                cmd_args.extend(target_ips)
            else:
                cmd_args.append(network)
            
            try:
                # Async Process with line-by-line parsing
                proc = await asyncio.create_subprocess_exec(
                    *cmd_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                async def _read_stream(stream: asyncio.StreamReader):
                    while True:
                        line = await stream.readline()
                        if not line:
                            break
                        line_str = line.decode(errors='ignore').strip()
                        
                        # Example: "Nmap scan report for sleeper-pc (192.168.100.10)"
                        if "Nmap scan report for" in line_str:
                            match = re.search(r"Nmap scan report for (?:(.+?) \()?((\d{1,3}\.){3}\d{1,3})\)?", line_str)
                            if match:
                                hostname = match.group(1).strip() if match.group(1) else None
                                ip_addr = match.group(2)
                                
                                if not any(h["ip"] == ip_addr for h in discovered):
                                    host_data = {"ip": ip_addr, "mac": None, "hostname": hostname}
                                    discovered.append(host_data)
                                    if host_found_callback:
                                        asyncio.create_task(host_found_callback(host_data))

                await _read_stream(proc.stdout)
                stderr_data, _ = await proc.communicate()
                await proc.wait()
                
                if proc.returncode != 0:
                    err_msg = stderr_data.decode(errors='ignore')
                    logger.warning(f"Nmap (async) failed with code {proc.returncode}: {err_msg}")

            except (NotImplementedError, AttributeError):
                # FALLBACK: Sync mode if async subprocess is not supported (e.g. some Windows loops)
                def _run_sync_nmap():
                    import subprocess
                    res = subprocess.run(cmd_args, capture_output=True, shell=False, text=True, errors='ignore')
                    return res.stdout, res.returncode

                loop = asyncio.get_event_loop()
                stdout_str, returncode = await loop.run_in_executor(None, _run_sync_nmap)
                
                if returncode == 0:
                    matches = re.findall(r"Nmap scan report for (?:(.+?) \()?((\d{1,3}\.){3}\d{1,3})\)?", stdout_str)
                    for hostname, ip_addr, _ in matches:
                        hostname = hostname.strip() if hostname else None
                        if not any(h["ip"] == ip_addr for h in discovered):
                            host_data = {"ip": ip_addr, "mac": None, "hostname": hostname}
                            discovered.append(host_data)
                            if host_found_callback:
                                asyncio.create_task(host_found_callback(host_data))
                else:
                    logger.error(f"Sync Nmap scan failed for targets: {cmd_args}")
        
        if discovered:
            if cancel_event and cancel_event.is_set():
                return discovered
            logger.info(f"Nmap found {len(discovered)} hosts. Resolving MACs via ARP/Neighbors...")
            await resolve_mac_addresses(discovered, target_ips)
            return discovered

    except Exception as e:
        logger.error(f"Nmap discovery encountered a fatal error: {e}", exc_info=True)

    # -- 2. Manual Fallback (Ping/TCP/ARP) ------------------------------------
    # This triggers if Nmap found nothing or failed
    logger.info("Falling back to manual Ping/TCP/ARP discovery loop.")

    async def _check_host(ip: str) -> Optional[Dict[str, Any]]:
        if cancel_event and cancel_event.is_set():
            return None
        if ip.startswith("169.254."):
            return None
            
        await trigger_arp_probe(ip)
        
        # Check Ping
        if await ping_host_async(ip, timeout):
            return {"ip": ip, "mac": None}
            
        # Check common ports
        for port in ALIVE_CHECK_PORTS:
            if await check_port_async(ip, port, 0.4):
                return {"ip": ip, "mac": None}
        return None

    sem = asyncio.Semaphore(max_workers)
    async def _sem_check(ip: str):
        async with sem:
            return await _check_host(ip)

    tasks = [_sem_check(ip) for ip in target_ips if not any(h["ip"] == ip for h in discovered)]
    if tasks:
        results = await asyncio.gather(*tasks)
        for r in results:
            if r:
                discovered.append(r)

    # Final MAC resolution for all hosts found in fallback
    await resolve_mac_addresses(discovered, target_ips)
    return discovered
