import asyncio
import logging
import socket
import subprocess
import re
import os
import threading
import sys
import json
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Common ports for alive check (Expanded for cross-VLAN IoT discovery where ARP fails and Ping is blocked)
ALIVE_CHECK_PORTS = [445, 135, 80, 22, 443, 8080, 8443, 1883, 8123, 5000, 8266, 9090]

OUI_MAP = {
    "00:00:0C": "Cisco", "00:01:42": "Cisco", "00:0C:CE": "Cisco", "00:1E:C9": "Cisco",
    "00:05:69": "VMware", "00:0C:29": "VMware", "00:50:56": "VMware",
    "08:00:27": "VirtualBox",
    "00:0D:3A": "Microsoft", "00:1D:D8": "Microsoft", "00:15:5D": "Hyper-V",
    "00:14:22": "Dell", "00:1D:09": "Dell", "00:21:70": "Dell",
    "00:11:32": "Synology", "00:11:32": "Synology",
    "00:17:88": "Philips Hue",
    "00:1D:C9": "Ubiquiti", "04:18:D6": "Ubiquiti", "24:A4:3C": "Ubiquiti", "78:8A:20": "Ubiquiti", "80:2A:A8": "Ubiquiti",
    "00:E0:4C": "Realtek",
    "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi", "E4:5F:01": "Raspberry Pi",
    "00:04:20": "Slim Devices (Logitech)",
    "00:04:4B": "NVIDIA",
    "00:10:FA": "Apple", "00:16:CB": "Apple", "00:1C:B3": "Apple", "00:1F:F3": "Apple",
}

def guess_vendor(mac: str) -> str:
    """Guess vendor from MAC address using local OUI map."""
    if not mac: return ""
    mac_clean = mac.replace("-", ":").upper()
    prefix = ":".join(mac_clean.split(":")[:3])
    return OUI_MAP.get(prefix, "")

async def _udp_probe_async(ip: str):
    """Send a tiny UDP packet to trigger ARP."""
    try:
        # NetBIOS Name Service (137) is great for triggering responses
        # Also try MDNS (5353) and LLMNR (5355)
        loop = asyncio.get_running_loop()
        for port in [137, 5353, 5355]:
            try:
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: asyncio.DatagramProtocol(),
                    remote_addr=(ip, port)
                )
                transport.sendto(b'\x00', (ip, port))
                transport.close()
            except: pass
    except:
        pass

def resolve_hostname_robust(ip: str) -> str:
    """
    Robust hostname resolution inspired by SchaeferAdminTool.
    Tries: 1. Win32 GetNameInfoW, 2. socket.gethostbyaddr, 3. ping -a
    """
    if not ip or ip.startswith("169.254."): return ""
    
    # 1. Try Win32 API (fastest & most accurate on Windows)
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
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

    # 2. Try Standard Socket
    try:
        name, _, _ = socket.gethostbyaddr(ip)
        if name and name != ip:
            return name
    except: pass

            # 3. Try ping -a fallback (Windows only shell method)
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
    
    # 4. Try Linux specific fallbacks (Avahi / Dig)
    if sys.platform != 'win32':
        # Try avahi-resolve (mDNS)
        try:
            res = subprocess.run(["avahi-resolve", "-a", ip], capture_output=True, text=True, timeout=1.0)
            if res.returncode == 0 and res.stdout:
                # Output format: "IP \t Hostname"
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

    return ""

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
    dns_server: str | None = None,
    host_found_callback = None
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
            
            # Optimization: If target_ips is small, scan IPs directly.
            if len(target_ips) < 50:
                targets = " ".join(target_ips)
            else:
                targets = network

            if network.startswith("169.254."):
                continue
                
            dns_flag = f"--dns-servers {dns_server}" if dns_server else ""
            cmd_str = f'nmap -sn {dns_flag} {targets}'
            
            try:
                # 1. Async Process with line-by-line parsing
                proc = await asyncio.create_subprocess_shell(
                    cmd_str,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                async def _read_stream(stream):
                    current_host = None
                    while True:
                        line = await stream.readline()
                        if not line: break
                        line_str = line.decode(errors='ignore').strip()
                        
                        # Parse Nmap output line-by-line
                        # Example: "Nmap scan report for sleeper-pc (192.168.100.10)"
                        if "Nmap scan report for" in line_str:
                            match = re.search(r"Nmap scan report for (?:(.+?) \()?((\d{1,3}\.){3}\d{1,3})\)?", line_str)
                            if match:
                                hostname = match.group(1).strip() if match.group(1) else None
                                ip = match.group(2)
                                
                                if ip not in [h["ip"] for h in discovered]:
                                    host_data = {"ip": ip, "mac": None, "hostname": hostname}
                                    discovered.append(host_data)
                                    if host_found_callback:
                                        # Trigger immediate callback for UI update
                                        asyncio.create_task(host_found_callback(host_data))
                await _read_stream(proc.stdout)
                stderr_data, _ = await proc.communicate()
                stderr_str = stderr_data.decode(errors='ignore')
                await proc.wait()
                returncode = proc.returncode
                if returncode != 0 and stderr_str:
                    logger.debug(f"Nmap returned code {returncode}. Error: {stderr_str}")

            except (NotImplementedError, AttributeError):
                # FALLBACK: Sync mode if async subprocess is not available (Windows Selector Loop)
                import subprocess
                def _run_sync_nmap():
                    res = subprocess.run(cmd_str, capture_output=True, shell=True, text=True, errors='ignore')
                    return res.stdout, res.returncode

                loop = asyncio.get_event_loop()
                stdout_str, returncode = await loop.run_in_executor(None, _run_sync_nmap)
                
                if returncode == 0:
                    matches = re.findall(r"Nmap scan report for (?:(.+?) \()?((\d{1,3}\.){3}\d{1,3})\)?", stdout_str)
                    for hostname, ip, _ in matches:
                        hostname = hostname.strip() if hostname else None
                        if not any(h["ip"] == ip for h in discovered):
                            host_data = {"ip": ip, "mac": None, "hostname": hostname}
                            discovered.append(host_data)
                            if host_found_callback:
                                asyncio.create_task(host_found_callback(host_data))
                elif stdout_str:
                    logger.debug(f"Sync Nmap returned code {returncode}. Output: {stdout_str}")
        
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
        if ip.startswith("169.254."): return None
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

def get_linux_neighbors() -> dict[str, str]:
    """Get MAC addresses via 'ip neighbor' (Linux native)."""
    if sys.platform == 'win32': return {}
    try:
        output = subprocess.check_output("ip neighbor show", shell=True, stderr=subprocess.STDOUT).decode(errors='ignore')
        mapping = {}
        for line in output.splitlines():
            # Format: 192.168.100.1 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE
            parts = line.split()
            if len(parts) >= 4:
                ip = parts[0]
                try:
                    # Check if it's a valid IP
                    socket.inet_aton(ip)
                    # Look for the 'lladdr' keyword and the following MAC
                    if 'lladdr' in parts:
                        mac_idx = parts.index('lladdr') + 1
                        if mac_idx < len(parts):
                            mac = parts[mac_idx].lower()
                            if len(mac) == 17:
                                mapping[ip] = mac
                except: continue
        return mapping
    except:
        return {}

def get_powershell_neighbors() -> dict[str, str]:
    """Get MAC addresses via PowerShell Get-NetNeighbor (Windows native)."""
    if sys.platform != 'win32': return {}
    try:
        ps_cmd = "Get-NetNeighbor | Select-Object IPAddress, LinkLayerAddress | ConvertTo-Json"
        output = subprocess.check_output(["powershell", "-Command", ps_cmd], shell=True).decode('cp850')
        data = json.loads(output)
        if isinstance(data, dict): data = [data]
        
        mapping = {}
        for item in data:
            ip = item.get("IPAddress")
            mac = item.get("LinkLayerAddress")
            if ip and mac and len(mac) >= 11: # Basic MAC validation
                mapping[ip] = mac.replace("-", ":").lower()
        return mapping
    except:
        return {}

async def resolve_mac_addresses(discovered_hosts: list[dict], all_target_ips: list[str] = None) -> list[dict]:
    """Resolve MAC addresses via system ARP table and find missing devices."""
    loop = asyncio.get_running_loop()
    
    try:
        # Get ARP table AND Native neighbors (run in executor as they are sync)
        arp_map = await loop.run_in_executor(None, get_local_arp_table)
        
        if sys.platform == 'win32':
            ps_map = await loop.run_in_executor(None, get_powershell_neighbors)
            arp_map.update(ps_map)
        else:
            linux_map = await loop.run_in_executor(None, get_linux_neighbors)
            arp_map.update(linux_map)
            
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
                    "hostname": None,
                    "vendor": guess_vendor(mac)
                })
            else:
                # Update existing vendor if missing
                for h in discovered_hosts:
                    if h["ip"] == ip and not h.get("vendor"):
                        h["vendor"] = guess_vendor(mac)
        
        # FINAL STEP: Resolve hostnames for all found devices that are missing them
        resolve_tasks = []
        for host in discovered_hosts:
            if not host.get("hostname"):
                async def _fill_name(h):
                    name = await loop.run_in_executor(None, resolve_hostname_robust, h["ip"])
                    if name: h["hostname"] = name
                resolve_tasks.append(_fill_name(host))
        
        if resolve_tasks:
            await asyncio.gather(*resolve_tasks)
                
    except Exception as e:
        logger.error(f"Error during ARP resolution: {e}")
    
    return discovered_hosts
