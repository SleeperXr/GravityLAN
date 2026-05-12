import asyncio
import logging
import re
import socket
import subprocess
import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.scanner.vendor import get_vendor

logger = logging.getLogger(__name__)

async def trigger_arp_probe(ip: str):
    """Send a tiny UDP packet to trigger an ARP entry for the target IP."""
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
            except OSError:
                pass
    except Exception:
        pass

def get_local_arp_table() -> Dict[str, str]:
    """Read and parse the system ARP table. Returns {ip: mac}."""
    try:
        # Try 'arp -a' first, then 'arp -g' as fallback
        try:
            stdout = subprocess.check_output("arp -a", shell=True, stderr=subprocess.STDOUT)
        except subprocess.SubprocessError:
            try:
                stdout = subprocess.check_output("arp -g", shell=True, stderr=subprocess.STDOUT)
            except subprocess.SubprocessError:
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

def get_linux_neighbors() -> Dict[str, str]:
    """Get MAC addresses via 'ip neighbor' (Linux native)."""
    if sys.platform == 'win32': return {}
    try:
        output = subprocess.check_output("ip neighbor show", shell=True, stderr=subprocess.STDOUT).decode(errors='ignore')
        mapping = {}
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                ip = parts[0]
                try:
                    socket.inet_aton(ip)
                    if 'lladdr' in parts:
                        mac_idx = parts.index('lladdr') + 1
                        if mac_idx < len(parts):
                            mac = parts[mac_idx].lower()
                            if len(mac) == 17:
                                mapping[ip] = mac
                except (socket.error, ValueError, IndexError):
                    continue
        return mapping
    except Exception:
        return {}

def get_powershell_neighbors() -> Dict[str, str]:
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
            if ip and mac and len(mac) >= 11:
                mapping[ip] = mac.replace("-", ":").lower()
        return mapping
    except Exception:
        return {}

async def resolve_mac_addresses(discovered_hosts: List[Dict[str, Any]], all_target_ips: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Robust MAC address resolution using multiple methods and active probing.
    
    Args:
        discovered_hosts: List of host dicts to update with MACs.
        all_target_ips: Optional filter to only include these IPs in the result.
    """
    loop = asyncio.get_running_loop()
    
    try:
        # 1. Collect ARP/Neighbor tables from all sources
        arp_map = await loop.run_in_executor(None, get_local_arp_table)
        
        if sys.platform == 'win32':
            ps_map = await loop.run_in_executor(None, get_powershell_neighbors)
            arp_map.update(ps_map)
        else:
            linux_map = await loop.run_in_executor(None, get_linux_neighbors)
            arp_map.update(linux_map)
            
        if not arp_map:
            return discovered_hosts

        # 2. Check which hosts are still missing a MAC
        missing_mac_ips = []
        for host in discovered_hosts:
            if host["ip"] in arp_map:
                host["mac"] = arp_map[host["ip"]]
            elif not host.get("mac"):
                missing_mac_ips.append(host["ip"])
        
        # 3. ACTIVE PROBING: Trigger ARP for missing entries
        if missing_mac_ips:
            logger.debug(f"Triggering active ARP probes for {len(missing_mac_ips)} hosts...")
            probe_tasks = []
            for ip in missing_mac_ips:
                probe_tasks.append(trigger_arp_probe(ip))
                # Simple ping also triggers ARP
                from app.scanner.utils import ping_host_async
                probe_tasks.append(ping_host_async(ip, timeout=0.2))
            
            await asyncio.gather(*probe_tasks)
            await asyncio.sleep(0.3)
            
            # Re-read tables after probes
            arp_map_retry = await loop.run_in_executor(None, get_local_arp_table)
            if arp_map_retry:
                for ip, mac in arp_map_retry.items():
                    arp_map[ip] = mac
                    for host in discovered_hosts:
                        if host["ip"] == ip: 
                            host["mac"] = mac

        # 4. Consolidate results
        for ip, mac in arp_map.items():
            if all_target_ips is not None and len(all_target_ips) > 0:
                if ip not in all_target_ips:
                    continue
            
            existing = next((h for h in discovered_hosts if h["ip"] == ip), None)
            if not existing:
                discovered_hosts.append({
                    "ip": ip, 
                    "mac": mac,
                    "hostname": None,
                    "vendor": get_vendor(mac)
                })
            else:
                if not existing.get("mac"):
                    existing["mac"] = mac
                if not existing.get("vendor"):
                    existing["vendor"] = get_vendor(mac)
                
    except Exception as e:
        logger.error(f"Error during ARP resolution: {e}")
    
    return discovered_hosts
