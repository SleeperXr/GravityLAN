"""Utility functions for network discovery and group management."""

import asyncio
import os
import re
import subprocess

import socket
import sys
import ipaddress
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.device import DeviceGroup
from app.schemas.scan import SubnetInfo
from datetime import datetime, timezone

def ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is timezone-aware (UTC). SQLite stores naive datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

logger = logging.getLogger(__name__)

DEFAULT_GROUPS = [
    {"name": "Firewalls", "icon": "shield", "sort_order": 0, "is_default": True},
    {"name": "Server", "icon": "server", "sort_order": 1, "is_default": True},
    {"name": "NAS / Storage", "icon": "hard-drive", "sort_order": 2, "is_default": True},
    {"name": "Web Interfaces", "icon": "globe", "sort_order": 3, "is_default": True},
    {"name": "Newly discovered", "icon": "sparkles", "sort_order": 99, "is_default": True},
]

GROUP_TYPE_MAP = {
    "firewall": "Firewalls",
    "server": "Server",
    "nas": "NAS / Storage",
    "webui": "Web Interfaces",
    "unknown": "Newly discovered",
}

async def ensure_default_groups(db: AsyncSession, commit: bool = True) -> dict[str, int]:
    """Create default groups if they don't exist."""
    result = await db.execute(select(DeviceGroup))
    existing = {g.name: g.id for g in result.scalars().all()}
    for group_data in DEFAULT_GROUPS:
        if group_data["name"] not in existing:
            group = DeviceGroup(**group_data)
            db.add(group)
            await db.flush()
            existing[group.name] = group.id
    if commit:
        await db.commit()
    return existing

def get_local_subnets() -> list[SubnetInfo]:
    """
    Ultimate Subnet Detector: Detects local interfaces using a multi-stage fallback.
    Inspired by SchaeferAdminTool's robust network discovery.
    """
    subnets: list[SubnetInfo] = []
    seen_subnets = set()
    
    # Filter list for common virtual/tunnel interfaces (Windows & Linux)
    VIRTUAL_IFACE_KEYWORDS = [
        'virtual', 'vbox', 'vmware', 'vEthernet', 'tailscale', 'zerotier', 
        'wsl', 'docker', 'tunnel', 'loopback', 'pseudo', 'veth'
    ]

    def add_subnet(name, ip, mask):
        if not ip or ip.startswith("127.") or ip.startswith("169.254."):
            return
            
        # Detect virtual/internal junk networks
        # On Linux, bridges often start with br-, docker, or veth
        is_virtual = any(kw.lower() in name.lower() for kw in VIRTUAL_IFACE_KEYWORDS)
        
        # Also check common internal IP ranges often used for docker bridges if we're unsure
        # but name-based detection is usually enough.
            
        try:
            network = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
            subnet_str = str(network)
            if subnet_str not in seen_subnets:
                subnets.append(SubnetInfo(
                    interface_name=name,
                    ip_address=ip,
                    subnet=subnet_str,
                    netmask=mask,
                    is_virtual=is_virtual
                ))
                seen_subnets.add(subnet_str)
        except (ValueError, OSError):
            pass

    # STAGE 1: psutil (Very reliable if installed)
    try:
        import psutil
        import socket
        interfaces = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for name, addrs in interfaces.items():
            # Skip if disabled or loopback
            if name in stats and not stats[name].isup: continue
            if "loopback" in name.lower() or name.startswith("lo"): continue
            
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    add_subnet(name, addr.address, addr.netmask or "255.255.255.0")
    except Exception:
        pass

    # STAGE 2: netifaces (Alternative if psutil is missing)
    if not subnets:
        try:
            import netifaces
            for iface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(iface)
                if netifaces.AF_INET in addrs:
                    for addr_info in addrs[netifaces.AF_INET]:
                        add_subnet(iface, addr_info.get("addr"), addr_info.get("netmask", "255.255.255.0"))
        except Exception:
            pass

    # STAGE 3: PowerShell (Native Windows Truth)
    if not subnets and sys.platform == 'win32':
        try:
            import subprocess
            import json
            ps_cmd = "Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias, IPAddress, PrefixLength | ConvertTo-Json"
            output = subprocess.check_output(["powershell", "-Command", ps_cmd]).decode('cp850')
            data = json.loads(output)
            if isinstance(data, dict): data = [data]
            for item in data:
                ip = item.get("IPAddress")
                prefix = item.get("PrefixLength")
                name = item.get("InterfaceAlias", "Windows Adapter")
                if ip and prefix:
                    # Convert prefix to mask
                    mask = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)
                    add_subnet(name, ip, mask)
        except Exception:
            pass

    # STAGE 4: Final socket fallback
    if not subnets:
        try:
            import socket
            hostname = socket.gethostname()
            _, _, ip_list = socket.gethostbyname_ex(hostname)
            for ip in ip_list:
                add_subnet("default", ip, "255.255.255.0")
        except (OSError, socket.error):
            pass
        
    return [s for s in subnets if not s.is_virtual]

async def check_port_async(ip: str, port: int, timeout: float = 0.4) -> bool:
    """Async check if a TCP port is open."""
    try:
        conn = asyncio.open_connection(ip, port)
        _, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError, ConnectionRefusedError):
        return False

async def ping_host_async(ip: str, timeout: float = 0.6) -> bool:
    """Run a single ICMP ping using async-compatible subprocess execution."""
    try:
        param = '-n' if os.name == 'nt' else '-c'
        timeout_val = str(int(timeout * 1000)) if os.name == 'nt' else str(max(1, int(timeout)))
        timeout_param = '-w' if os.name == 'nt' else '-W'
        
        command = ['ping', param, '1', timeout_param, timeout_val, ip]
        
        def _run_ping():
            # Use subprocess.run for Windows compatibility (avoids SelectorEventLoop issues)
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
        
        if proc.returncode == 0:
            # Windows ping returns 0 even if target is unreachable, check for TTL
            if "TTL=" in proc.stdout.upper():
                return True
        return False
    except Exception:
        return False
