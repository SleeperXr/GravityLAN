"""Utility functions for network discovery and group management."""

import socket
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

async def _ensure_default_groups(db: AsyncSession, commit: bool = True) -> dict[str, int]:
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

def _get_local_subnets() -> list[SubnetInfo]:
    """Detect local network interfaces and their subnets."""
    subnets: list[SubnetInfo] = []
    try:
        import netifaces
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET in addrs:
                for addr_info in addrs[netifaces.AF_INET]:
                    ip = addr_info.get("addr", "")
                    mask = addr_info.get("netmask", "255.255.255.0")
                    if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                        try:
                            network = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
                            subnets.append(SubnetInfo(
                                interface_name=iface,
                                ip_address=ip,
                                subnet=str(network),
                                netmask=mask,
                            ))
                        except: continue
    except ImportError:
        hostname = socket.gethostname()
        try:
            ip = socket.gethostbyname(hostname)
            if ip and not ip.startswith("127."):
                network = ipaddress.IPv4Network(f"{ip}/24", strict=False)
                subnets.append(SubnetInfo(
                    interface_name="default",
                    ip_address=ip,
                    subnet=str(network),
                    netmask="255.255.255.0",
                ))
        except socket.error:
            pass
    return subnets
