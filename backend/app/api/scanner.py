"""Network scanner API — start scans, get status, WebSocket live updates."""

import asyncio
import ipaddress
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.device import DiscoveredHost
from app.models.setting import Setting
from app.schemas.scan import (
    ScanProgress,
    ScanRequest,
    ScanStatus,
    SubnetInfo,
)
from app.schemas.device import DiscoveredHostResponse, DiscoveredHostUpdate
from app.scanner.planner import run_planner_scan
from app.scanner.dashboard import run_dashboard_scan
from app.scanner.sync import sync_host_to_db
from app.scanner.utils import _get_local_subnets

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scanner", tags=["scanner"])

# Global scan state
_scan_task: asyncio.Task | None = None
_cancel_event = asyncio.Event()
_last_progress: ScanProgress | None = None
_scan_active = False

@router.get("/subnets", response_model=list[SubnetInfo])
async def get_subnets() -> list[SubnetInfo]:
    """Get available network interfaces and subnets for scanning."""
    return _get_local_subnets()

@router.get("/test")
async def test_scanner():
    """Test endpoint to verify scanner API availability."""
    return {"status": "ok", "module": "scanner"}

@router.get("/scan-ip")
async def scan_ip(ip: str):
    """Perform a robust scan on a specific IP."""
    from app.scanner.port_scanner import nmap_scan, scan_ports
    
    logger.info(f"Manual scan requested for {ip}")
    
    dns_server = None
    async with async_session() as db:
        dns_q = await db.execute(select(Setting).where(Setting.key == "dns.server"))
        dns_s = dns_q.scalar_one_or_none()
        if dns_s:
            dns_server = dns_s.value

    ports = await nmap_scan(ip, dns_server=dns_server)
    if not ports:
        ports = await scan_ports(ip, gentle=False, timeout=0.5)
    return {"ip": ip, "ports": ports, "timestamp": datetime.now()}

@router.post("/quick-subnet-scan")
async def quick_subnet_scan(subnets: str):
    """Turbo-fast subnet refresh (ARP + ICMP) via Planner scan."""
    subnet_list = [s.strip() for s in subnets.split(",") if s.strip()]
    await run_planner_scan(subnet_list)
    return {"status": "ok", "message": "Quick scan triggered"}

@router.post("/discover")
async def discover_subnet(request: ScanRequest) -> dict:
    """Trigger a full host discovery on subnets."""
    return await start_scan(request)

@router.get("/status", response_model=ScanProgress)
async def get_scan_status() -> ScanProgress:
    """Get current scan job status."""
    if _last_progress:
        return _last_progress
    return ScanProgress(status=ScanStatus.IDLE, message="No scan active")

@router.get("/discovered", response_model=list[DiscoveredHostResponse])
async def get_discovered_hosts():
    """Get all hosts from the persistent discovery table."""
    async with async_session() as db:
        result = await db.execute(
            select(DiscoveredHost)
            .where(or_(DiscoveredHost.is_online == True, DiscoveredHost.is_monitored == True))
            .order_by(DiscoveredHost.is_monitored.desc(), DiscoveredHost.last_seen.desc())
        )
        return result.scalars().all()

@router.patch("/discovered/{host_id}", response_model=DiscoveredHostResponse)
async def patch_discovered_host(host_id: int, update: DiscoveredHostUpdate):
    """Update a discovered host's name or monitoring status."""
    async with async_session() as db:
        host = await db.get(DiscoveredHost, host_id)
        if not host:
            raise HTTPException(status_code=404, detail="Host not found")
        update_data = update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(host, field, value)
        await db.commit()
        await db.refresh(host)
        return host

@router.post("/start")
async def start_scan(request: ScanRequest):
    """Manually trigger a Network Planner scan (ARP + Ping + DNS)."""
    global _scan_active, _scan_task, _cancel_event
    if _scan_active:
        return {"status": "error", "message": "Scan already in progress"}

    _scan_active = True
    _cancel_event = asyncio.Event()
    
    async def progress_cb(msg):
        await _broadcast(ScanProgress(status=ScanStatus.RUNNING, message=msg, progress=50))

    async def run_scan_task():
        global _scan_active
        try:
            await run_planner_scan(request.subnets, progress_callback=progress_cb)
            await _broadcast(ScanProgress(status=ScanStatus.IDLE, message="Scan complete"))
        except Exception as e:
            logger.error(f"Manual scan failed: {e}")
            await _broadcast(ScanProgress(status=ScanStatus.ERROR, message=f"Scan error: {str(e)}"))
        finally:
            _scan_active = False

    _scan_task = asyncio.create_task(run_scan_task())
    return {"status": "ok", "message": "Planner scan started"}

@router.post("/stop")
async def stop_scan() -> dict:
    """Cancel a running scan."""
    global _cancel_event
    _cancel_event.set()
    return {"status": "cancelling"}

@router.get("/live-discovery")
@router.get("/live-discovery/")
async def live_discovery(subnets: str) -> list[dict]:
    """Perform a fast ICMP/ARP discovery and return the results."""
    subnet_list = [s.strip() for s in subnets.split(",") if s.strip()]
    
    from app.scanner.discovery import discover_hosts_simple, resolve_mac_addresses
    from app.scanner.hostname import resolve_hostnames

    # Get DNS server from settings
    dns_server = None
    async with async_session() as db:
        res_dns = await db.execute(select(Setting).where(Setting.key == "dns.server"))
        dns_s = res_dns.scalar_one_or_none()
        if dns_s: dns_server = dns_s.value

    all_hosts = []
    for subnet in subnet_list:
        try:
            logger.info(f"Live-discovery triggered for: {subnet}")
            if "/" not in subnet: 
                if subnet.count(".") == 2: # e.g. 192.168.100
                    subnet = f"{subnet}.0/24"
                else:
                    subnet = f"{subnet}/24"
            
            # Convert subnet to list of IPs for the discovery function
            import ipaddress
            net = ipaddress.ip_network(subnet, strict=False)
            target_ips = [str(ip) for ip in net.hosts()]
            
            # Perform host discovery
            from app.config import settings
            alive_hosts = await discover_hosts_simple(target_ips, dns_server=dns_server, timeout=settings.scan_timeout)
            if alive_hosts:
                # Resolve MACs and Hostnames
                alive_hosts = await resolve_mac_addresses(alive_hosts)
                await resolve_hostnames(alive_hosts, dns_server=dns_server)
                
                # Sync each host to DB
                for host in alive_hosts:
                    await sync_host_to_db(
                        ip=host["ip"], 
                        mac=host.get("mac"), 
                        hostname=host.get("hostname"),
                        vendor=host.get("vendor")
                    )
            
            all_hosts.extend(alive_hosts)
        except Exception as e:
            logger.error(f"Live-discovery error for {subnet}: {e}")
            
    return all_hosts

# --- WebSocket for live scan updates ---
_ws_clients: list[WebSocket] = []

@router.websocket("/ws")
async def scan_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time scan progress updates."""
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)

async def _broadcast(data: ScanProgress) -> None:
    """Send a message to all connected WebSocket clients."""
    global _last_progress
    _last_progress = data
    data_dict = data.model_dump(mode="json")
    disconnected: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_json(data_dict)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in _ws_clients:
            _ws_clients.remove(ws)
