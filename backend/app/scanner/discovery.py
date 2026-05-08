import asyncio
import logging
import socket
import subprocess
import re
import os
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Common ports for alive check (Expanded for cross-VLAN IoT discovery where ARP fails and Ping is blocked)
ALIVE_CHECK_PORTS = [445, 135, 80, 22, 443, 8080, 8443, 1883, 8123, 5000, 8266, 9090]

async def _udp_probe_async(ip: str):
    """Send a tiny UDP packet to trigger ARP."""
    try:
        # NetBIOS Name Service (137) is great for triggering responses
        transport, _ = await asyncio.get_event_loop().create_datagram_endpoint(
            lambda: asyncio.DatagramProtocol(),
            remote_addr=(ip, 137)
        )
        transport.sendto(b'\x00', (ip, 137))
        transport.close()
    except:
        pass

async def _check_port_async(ip: str, port: int, timeout: float = 0.4) -> bool:
    """Async check if a port is open."""
    try:
        conn = asyncio.open_connection(ip, port)
        _, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except:
        return False

async def _ping_host_async(ip: str, timeout: float = 0.6) -> bool:
    """Run a single ICMP ping using async subprocess."""
    try:
        param = '-n' if os.name == 'nt' else '-c'
        # On Linux, -W is in seconds. Ensure it's at least 1 if we use int(), or use the float if supported.
        # iputils-ping -W expects an integer for older versions, or allows decimals in newer ones.
        # We'll use 1 as a safe minimum for int conversion.
        timeout_val = str(int(timeout * 1000)) if os.name == 'nt' else str(max(1, int(timeout)))
        timeout_param = '-w' if os.name == 'nt' else '-W'
        
        command = ['ping', param, '1', timeout_param, timeout_val, ip]
        def _run_ping():
            # Use subprocess.run directly instead of asyncio subprocess to avoid SelectorEventLoop bugs on Windows
            return subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

        loop = asyncio.get_running_loop()
        proc = await loop.run_in_executor(None, _run_ping)
        
        # Windows ping returns 0 even for "Destination host unreachable"
        # The only reliable way to know if it actually replied is to check for "TTL=" or "ttl="
        if proc.returncode == 0:
            if "TTL=" in proc.stdout.upper():
                return True
        return False
    except:
        return False

async def discover_hosts_simple(
    target_ips: list[str],
    timeout: float = 1.0,
    max_workers: int = 30,
    cancel_event: asyncio.Event | None = None,
    mode: str = "gentle",
    dns_server: str | None = None
) -> list[dict]:
    """Highly accurate host discovery using Nmap (Fast) + ARP fallback."""
    discovered: list[dict] = []
    
    # Try Nmap -sn first (Fast & Accurate on local networks)
    try:
        import ipaddress
        networks = set()
        for ip in target_ips:
            try:
                net = ipaddress.IPv4Interface(f"{ip}/24").network
                networks.add(str(net))
            except: pass
        
        for network in networks:
            if cancel_event and cancel_event.is_set(): break
            logger.info(f"Running nmap discovery on {network} (DNS: {dns_server or 'System'})...")
            
            # Use --dns-servers for better internal name resolution if provided
            dns_flag = f"--dns-servers {dns_server}" if dns_server else ""
            cmd_str = f'nmap -sn {dns_flag} {network}'
            
            try:
                # Try async first
                proc = await asyncio.create_subprocess_shell(
                    cmd_str,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                async def _monitor_cancel():
                    if cancel_event:
                        await cancel_event.wait()
                        if proc.returncode is None:
                            try: 
                                proc.terminate()
                                await asyncio.sleep(0.2)
                                if proc.returncode is None: proc.kill()
                            except: pass
                
                monitor_task = asyncio.create_task(_monitor_cancel())
                try:
                    stdout, stderr = await proc.communicate()
                except Exception as e:
                    logger.warning(f"Nmap communication error for {network}: {e}")
                    stdout, stderr = b"", b""
                finally:
                    monitor_task.cancel()
                
                returncode = proc.returncode

            except NotImplementedError:
                # FALLBACK: Use ThreadPoolExecutor for Windows loops that don't support subprocesses
                logger.info("Async subprocess not supported, falling back to ThreadPool for Nmap")
                import subprocess
                from concurrent.futures import ThreadPoolExecutor
                
                def _run_sync_nmap():
                    try:
                        res = subprocess.run(cmd_str, capture_output=True, shell=True, text=False)
                        return res.stdout, res.stderr, res.returncode
                    except Exception as e:
                        logger.error(f"Sync Nmap failed: {e}")
                        return b"", b"", 1

                loop = asyncio.get_event_loop()
                with ThreadPoolExecutor() as pool:
                    stdout, stderr, returncode = await loop.run_in_executor(pool, _run_sync_nmap)

            if returncode == 0:
                output = stdout.decode(errors='ignore')
                # Match both "Nmap scan report for 1.2.3.4" and "Nmap scan report for host (1.2.3.4)"
                matches = re.findall(r"Nmap scan report for (?:(.+?) \()?((\d{1,3}\.){3}\d{1,3})\)?", output)
                for hostname, ip, _ in matches:
                    hostname = hostname.strip() if hostname else None
                    if ip in target_ips and not any(h["ip"] == ip for h in discovered):
                        discovered.append({"ip": ip, "mac": None, "hostname": hostname})
            else:
                err = stderr.decode(errors='ignore')
                logger.debug(f"Nmap returned code {returncode} for {network}. Error: {err}")
        
        if len(discovered) > 0:
            if cancel_event and cancel_event.is_set(): return discovered
            logger.info(f"Nmap found {len(discovered)} hosts. Resolving MACs...")
            await resolve_mac_addresses(discovered, target_ips)
            return discovered

    except Exception as e:
        logger.error(f"Nmap discovery failed, falling back to manual: {str(e)}", exc_info=True)

    # Fallback to manual ping/TCP loop
    async def _check_host(ip: str):
        if cancel_event and cancel_event.is_set(): return None
        await _udp_probe_async(ip)
        if await _ping_host_async(ip, timeout):
            return {"ip": ip, "mac": None}
        for port in ALIVE_CHECK_PORTS:
            if await _check_port_async(ip, port, 0.4):
                return {"ip": ip, "mac": None}
        return None

    sem = asyncio.Semaphore(max_workers)
    async def _sem_check(ip: str):
        async with sem: return await _check_host(ip)

    tasks = [_sem_check(ip) for ip in target_ips]
    results = await asyncio.gather(*tasks)
    for r in results:
        if r: discovered.append(r)

    await resolve_mac_addresses(discovered, target_ips)
    return discovered

def get_local_arp_table() -> dict[str, str]:
    """Read and parse the system ARP table. Returns {ip: mac}."""
    try:
        # Try 'arp -a' first, then 'arp -g' as fallback
        try:
            stdout = subprocess.check_output("arp -a", shell=True, stderr=subprocess.STDOUT)
        except:
            try:
                stdout = subprocess.check_output("arp -g", shell=True, stderr=subprocess.STDOUT)
            except:
                return {}
        
        if not stdout:
            return {}

        output = ""
        for encoding in ['cp850', 'utf-8', 'latin-1', 'ascii']:
            try:
                output = stdout.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        
        if not output:
            return {}

        # Improved ARP parsing for Windows/Linux (IP   MAC   Type)
        arp_map = {}
        for line in output.splitlines():
            line = line.strip()
            # Match IP and MAC
            ip_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
            mac_match = re.search(r"([0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2}[:-][0-9a-fA-F]{2})", line)
            
            if ip_match and mac_match:
                ip = ip_match.group(1)
                mac = mac_match.group(1).replace("-", ":").lower()
                # Skip broadcast/multicast
                if not mac.startswith("ff:ff:ff") and not mac.startswith("01:00:5e") and mac != "00:00:00:00:00:00":
                    arp_map[ip] = mac
        return arp_map
    except Exception as e:
        logger.error(f"ARP command failed: {e}")
        return {}

async def resolve_mac_addresses(discovered_hosts: list[dict], all_target_ips: list[str] = None) -> list[dict]:
    """Resolve MAC addresses via system ARP table and find missing devices."""
    loop = asyncio.get_running_loop()
    
    try:
        # Get ARP table (run in executor as it's a subprocess call)
        arp_map = await loop.run_in_executor(None, get_local_arp_table)
        if not arp_map:
            return

        # Update already discovered hosts and collect those missing a MAC
        missing_mac_ips = []
        for host in discovered_hosts:
            if host["ip"] in arp_map:
                host["mac"] = arp_map[host["ip"]]
            elif not host.get("mac"):
                missing_mac_ips.append(host["ip"])
        
        # ACTIVE PROBING: If some hosts are missing a MAC, try to trigger ARP entries
        if missing_mac_ips:
            logger.debug(f"Triggering ARP for {len(missing_mac_ips)} hosts missing a MAC...")
            # Send probes in parallel
            probe_tasks = []
            for ip in missing_mac_ips:
                probe_tasks.append(_udp_probe_async(ip))
                probe_tasks.append(_ping_host_async(ip, timeout=0.2))
            await asyncio.gather(*probe_tasks)
            
            # Re-read ARP table once more after a tiny delay
            await asyncio.sleep(0.3)
            arp_map_retry = await loop.run_in_executor(None, get_local_arp_table)
            if arp_map_retry:
                for ip, mac in arp_map_retry.items():
                    arp_map[ip] = mac
                    for host in discovered_hosts:
                        if host["ip"] == ip: 
                            host["mac"] = mac

        # If all_target_ips is empty, we want EVERYTHING from the ARP table (passive mode)
        # If it contains IPs, we only want the intersection.
        for ip, mac in arp_map.items():
            if all_target_ips is not None and len(all_target_ips) > 0:
                if ip not in all_target_ips:
                    continue
            
            # Check if already in discovered
            if not any(h["ip"] == ip for h in discovered_hosts):
                discovered_hosts.append({
                    "ip": ip, 
                    "mac": mac,
                    "hostname": None
                })
                
    except Exception as e:
        logger.error(f"Error during ARP resolution: {e}")
    
    return discovered_hosts
