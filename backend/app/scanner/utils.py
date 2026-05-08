"""Utility functions for network discovery and group management."""

import socket
import sys
import ipaddress
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.device import DeviceGroup
from app.schemas.scan import SubnetInfo

logger = logging.getLogger(__name__)

DEFAULT_GROUPS = [
    {"name": "Firewalls", "icon": "shield", "sort_order": 0, "is_default": True},
    {"name": "Server", "icon": "server", "sort_order": 1, "is_default": True},
    {"name": "NAS / Storage", "icon": "hard-drive", "sort_order": 2, "is_default": True},
    {"name": "Web Interfaces", "icon": "globe", "sort_order": 3, "is_default": True},
    {"name": "Neu entdeckt", "icon": "sparkles", "sort_order": 99, "is_default": True},
]

GROUP_TYPE_MAP = {
    "firewall": "Firewalls",
    "server": "Server",
    "nas": "NAS / Storage",
    "webui": "Web Interfaces",
    "unknown": "Neu entdeckt",
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
        'wsl', 'docker', 'tunnel', 'loopback', 'pseudo', 'veth', 'br-', 'virbr', 'bridge'
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
        except: pass

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
    except Exception: pass

    # STAGE 2: netifaces (Alternative if psutil is missing)
    if not subnets:
        try:
            import netifaces
            for iface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(iface)
                if netifaces.AF_INET in addrs:
                    for addr_info in addrs[netifaces.AF_INET]:
                        add_subnet(iface, addr_info.get("addr"), addr_info.get("netmask", "255.255.255.0"))
        except Exception: pass

    # STAGE 3: PowerShell (Native Windows Truth)
    if not subnets and sys.platform == 'win32':
        try:
            import subprocess
            import json
            ps_cmd = "Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias, IPAddress, PrefixLength | ConvertTo-Json"
            output = subprocess.check_output(["powershell", "-Command", ps_cmd], shell=True).decode('cp850')
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
        except Exception: pass

    # STAGE 4: Final socket fallback
    if not subnets:
        try:
            import socket
            hostname = socket.gethostname()
            _, _, ip_list = socket.gethostbyname_ex(hostname)
            for ip in ip_list:
                add_subnet("default", ip, "255.255.255.0")
        except: pass
        
    return subnets
