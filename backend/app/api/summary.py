"""Summary API endpoint for GravityLAN."""

import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.api.auth import get_current_admin
from app.models.device import Device, Service
from app.models.agent import AgentToken, DeviceMetrics
from app.schemas.summary import SummaryResponse, ActiveIssue
from app.scanner.utils import ensure_utc
from app.api.scanner import state
from app.schemas.scan import ScanStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/summary", tags=["summary"])

@router.get("", response_model=SummaryResponse)
async def get_summary(
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
) -> SummaryResponse:
    """Fetch aggregated system metrics and status summary."""
    now = datetime.now(timezone.utc)
    
    # 1. Device counts
    devices_res = await db.execute(select(Device.id, Device.is_online))
    devices = devices_res.all()
    total_devices = len(devices)
    online_devices = sum(1 for d in devices if d.is_online)
    offline_devices = total_devices - online_devices
    
    # 2. Agent counts and metrics
    agents_res = await db.execute(select(AgentToken))
    agents = agents_res.scalars().all()
    total_agents = len(agents)
    
    active_device_ids = []
    for agent in agents:
        last_seen = ensure_utc(agent.last_seen)
        is_active = bool(last_seen and (now - last_seen).total_seconds() < 300)
        if is_active:
            active_device_ids.append(agent.device_id)
            
    active_agents_count = len(active_device_ids)
    
    avg_cpu = 0.0
    avg_ram = 0.0
    
    if active_device_ids:
        # Fetch the latest metrics for each active device
        metrics_res = await db.execute(
            select(DeviceMetrics).where(DeviceMetrics.id.in_(
                select(func.max(DeviceMetrics.id)).group_by(DeviceMetrics.device_id)
            ))
        )
        latest_metrics = {m.device_id: m for m in metrics_res.scalars().all()}
        
        cpu_vals = []
        ram_vals = []
        for dev_id in active_device_ids:
            m = latest_metrics.get(dev_id)
            if m:
                cpu_vals.append(m.cpu_percent)
                ram_vals.append(m.ram_percent)
                
        if cpu_vals:
            avg_cpu = sum(cpu_vals) / len(cpu_vals)
        if ram_vals:
            avg_ram = sum(ram_vals) / len(ram_vals)
            
    # 3. Scanner state and last scan time
    scanner_status = "idle"
    if state.last_progress:
        scanner_status = state.last_progress.status.value
        
    last_scan = None
    last_seen_res = await db.execute(select(func.max(Device.last_seen)))
    last_scan_dt = last_seen_res.scalar_one_or_none()
    if last_scan_dt:
        last_scan = ensure_utc(last_scan_dt)
    elif state.last_progress:
        last_scan = ensure_utc(state.last_progress.timestamp)
        
    # 4. Active issues (offline agents and down services)
    active_issues = []
    
    # Offline agents
    res_inactive_agents = await db.execute(
        select(Device, AgentToken)
        .join(AgentToken, Device.id == AgentToken.device_id, isouter=True)
        .where(Device.has_agent == True)
    )
    for dev, agent_token in res_inactive_agents.all():
        is_agent_active = False
        if agent_token and agent_token.is_active and agent_token.last_seen:
            last_seen = ensure_utc(agent_token.last_seen)
            if (now - last_seen).total_seconds() < 300:
                is_agent_active = True
                
        if not is_agent_active:
            last_seen_str = "never"
            if agent_token and agent_token.last_seen:
                last_seen_str = ensure_utc(agent_token.last_seen).isoformat()
            active_issues.append({
                "type": "agent_offline",
                "device_id": dev.id,
                "device_name": dev.display_name or dev.hostname or dev.ip,
                "details": f"Agent has not reported since {last_seen_str}"
            })
            
    # Down services
    res_down_services = await db.execute(
        select(Service, Device)
        .join(Device, Service.device_id == Device.id)
        .where(Service.is_up == False)
    )
    for svc, dev in res_down_services.all():
        active_issues.append({
            "type": "service_down",
            "device_id": dev.id,
            "device_name": dev.display_name or dev.hostname or dev.ip,
            "details": f"Service {svc.name} on port {svc.port} is down"
        })
        
    return SummaryResponse(
        devices={
            "total": total_devices,
            "online": online_devices,
            "offline": offline_devices
        },
        agents={
            "total": total_agents,
            "active": active_agents_count,
            "avg_cpu": round(avg_cpu, 2),
            "avg_ram": round(avg_ram, 2)
        },
        scanner={
            "status": scanner_status,
            "last_scan": last_scan
        },
        active_issues=active_issues
    )

issues_router = APIRouter(prefix="/api/issues", tags=["issues"])

@issues_router.get("", response_model=list[ActiveIssue])
async def get_active_issues(
    token: str = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
) -> list[ActiveIssue]:
    """Exposes active issues as a standalone list."""
    summary = await get_summary(token, db)
    return summary.active_issues
