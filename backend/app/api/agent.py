"""Agent API — Handles incoming metrics from deployed agents and provides real-time status."""

import asyncio
import json
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


from app.scanner.utils import ensure_utc

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    Response,
)
from fastapi.responses import PlainTextResponse, FileResponse
from sqlalchemy import delete, desc, select, func, case, and_
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.config import settings
from app.database import async_session, get_db
from app.models.agent import AgentConfig, DeviceMetrics, AgentToken
from app.models.device import Device, DeviceHistory, DiscoveredHost
from app.api.auth import get_current_admin
from app.schemas.agent import (
    AgentReportPayload,
    AgentReportResponse,
    AgentStatusResponse,
    AgentDeployRequest,
    AgentDeployResponse,
    AgentConfigUpdate,
    AgentConfigResponse,
    MetricsHistoryResponse,
    AgentsOverviewResponse,
    AgentSummary,
    GlobalMetricPoint,
    GlobalMetricsResponse,
)
from app.services.agent_deployer import deploy_agent, remove_agent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])

from app.version import VERSION as LATEST_AGENT_VERSION

# Global caches for real-time dashboard updates
_latest_metrics: Dict[int, Dict[str, Any]] = {}
_ws_subscribers: Dict[int, set[WebSocket]] = {}
_setting_cache: Dict[str, Any] = {}
_setting_cache_time: datetime = datetime.min.replace(tzinfo=timezone.utc)

# Maximum metrics rows to keep per device (prevents unbounded growth)
MAX_METRICS_PER_DEVICE = 2880  # ~24h at 30s intervals


# ---------------------------------------------------------------------------
# Report Endpoint (Agent -> Server)
# ---------------------------------------------------------------------------

@router.post("/report", response_model=AgentReportResponse)
async def receive_report(
    payload: AgentReportPayload,
    request: Request,
    authorization: str = Header(...),
) -> AgentReportResponse:
    """
    Receive a metrics report from a deployed agent.
    
    Includes advanced auto-healing logic to recover agent sessions after 
    database resets or device re-discovery.
    
    Args:
        payload: The metrics data from the agent.
        request: FastAPI request object (used for client IP).
        authorization: Bearer token for authentication.
        
    Returns:
        AgentReportResponse with status and optional command config.
        
    Raises:
        HTTPException: 401 if token is invalid or 404 if device is missing.
    """
    token = authorization.replace("Bearer ", "").strip()
    client_ip = request.client.host if request.client else None

    async with async_session() as db:
        # 1. Validate token (Read-only phase)
        result = await db.execute(
            select(AgentToken).where(
                AgentToken.token == token, 
                AgentToken.is_active.is_(True)
            )
        )
        agent_token = result.scalar_one_or_none()

        # 2. Settings Cache (Global)
        global _setting_cache, _setting_cache_time
        now = datetime.now(timezone.utc)
        if "allow_auto_adopt" not in _setting_cache or (now - _setting_cache_time).total_seconds() > 300:
            from app.models.setting import Setting
            adopt_res = await db.execute(select(Setting).where(Setting.key == "agent.allow_auto_adoption"))
            allow_adopt_setting = adopt_res.scalar_one_or_none()
            _setting_cache["allow_auto_adopt"] = allow_adopt_setting.value.lower() == "true" if allow_adopt_setting else False
            _setting_cache_time = now
        allow_auto_adopt = _setting_cache["allow_auto_adopt"]

        # 3. Handle Token Mismatch / Pending Adoption
        if not agent_token and client_ip:
            dev_result = await db.execute(select(Device).where(Device.ip == client_ip))
            device = dev_result.scalar_one_or_none()
            if device and device.id == payload.device_id:
                logger.warning(f"Token mismatch for device {device.id} ({client_ip}). Storing pending_token.")
                token_res = await db.execute(select(AgentToken).where(AgentToken.device_id == device.id))
                token_obj = token_res.scalar_one_or_none()
                if token_obj:
                    token_obj.pending_token = token
                    token_obj.pending_at = datetime.now(timezone.utc)
                else:
                    new_token = AgentToken(device_id=device.id, token="TEMP_INVALID_" + token[:8], pending_token=token, pending_at=datetime.now(timezone.utc))
                    db.add(new_token)
                await db.commit()
            raise HTTPException(status_code=401, detail="Invalid token. Manual adoption required.")
        elif not agent_token:
            raise HTTPException(status_code=401, detail="Invalid token.")

        # 4. Main Persistence Transaction (with Retry)
        effective_device_id = agent_token.device_id
        config_to_send = None

        for attempt in range(5):
            try:
                # Refresh objects in this transaction
                db_token = await db.get(AgentToken, agent_token.id)
                device = await db.get(Device, effective_device_id)

                if not device:
                    # Fallback mapping if device was deleted/recreated
                    dev_res = await db.execute(select(Device).where(Device.ip == client_ip))
                    device = dev_res.scalar_one_or_none()
                    if device:
                        db_token.device_id = device.id
                        effective_device_id = device.id
                    else:
                        raise HTTPException(status_code=404, detail="Device mapping lost")

                # Update metadata (throttled)
                now = datetime.now(timezone.utc)
                last_seen = ensure_utc(db_token.last_seen)
                if not last_seen or (now - last_seen).total_seconds() > 60:
                    db_token.last_seen = now
                    device.is_online = True
                    device.last_seen = now
                
                if db_token.agent_version != payload.agent_version:
                    db_token.agent_version = payload.agent_version
                device.has_agent = True

                # Add Metrics
                metrics = DeviceMetrics(
                    device_id=effective_device_id,
                    cpu_percent=payload.cpu_percent,
                    ram_used_mb=payload.ram.used_mb,
                    ram_total_mb=payload.ram.total_mb,
                    ram_percent=payload.ram.percent,
                    disk_json=json.dumps([d.model_dump() for d in payload.disk]) if payload.disk else None,
                    temperature=payload.temperature,
                    net_json=json.dumps(payload.network) if payload.network else None,
                )
                db.add(metrics)

                # Fetch Config
                config_res = await db.execute(select(AgentConfig).where(AgentConfig.device_id == effective_device_id))
                agent_config = config_res.scalar_one_or_none()
                if not agent_config:
                    agent_config = AgentConfig(device_id=effective_device_id)
                    db.add(agent_config)
                    await db.flush()

                config_to_send = {
                    "version": agent_config.version,
                    "interval": agent_config.interval,
                    "disk_paths": agent_config.disk_paths,
                    "enable_temp": agent_config.enable_temp
                }

                await db.commit()
                break

            except (StaleDataError, OperationalError) as e:
                await db.rollback()
                if attempt < 4:
                    wait = (attempt + 1) * 0.3
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"Agent report persistence failed after 5 attempts: {e}")
                raise

        # 8. Broadcast to WebSocket subscribers
        snapshot = {
            "device_id": effective_device_id,
            "cpu_percent": payload.cpu_percent,
            "ram": payload.ram.model_dump(),
            "disk": [d.model_dump() for d in payload.disk],
            "temperature": payload.temperature,
            "network": payload.network,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        _latest_metrics[effective_device_id] = snapshot
        
        if effective_device_id in _ws_subscribers:
            dead_links = set()
            for ws in _ws_subscribers[effective_device_id]:
                try:
                    await ws.send_json({"type": "metrics", "data": snapshot})
                except Exception as e:
                    logger.debug(f"Metrics WebSocket error for device {effective_device_id}: {e}")
                    dead_links.add(ws)
            _ws_subscribers[effective_device_id] -= dead_links

        return AgentReportResponse(
            status="success",
            config_version=config_to_send["version"],
            config={
                "interval": config_to_send["interval"],
                "disk_paths": config_to_send["disk_paths"],
                "enable_temp": config_to_send["enable_temp"]
            },
            commands=[]
        )


@router.get("/config/{device_id}", response_model=AgentConfigResponse)
async def get_agent_config(device_id: int, db: AsyncSession = Depends(get_db)):
    """Get the persistent configuration for a specific agent."""
    config_res = await db.execute(select(AgentConfig).where(AgentConfig.device_id == device_id))
    config = config_res.scalar_one_or_none()
    
    if not config:
        # Create default config if missing
        config = AgentConfig(device_id=device_id)
        db.add(config)
        await db.commit()
        await db.refresh(config)
        
    return AgentConfigResponse(
        device_id=device_id,
        interval=config.interval,
        disk_paths=config.disk_paths,
        enable_temp=config.enable_temp
    )


@router.patch("/config/{device_id}", response_model=AgentConfigResponse)
async def update_agent_config(
    device_id: int, 
    update: AgentConfigUpdate, 
    db: AsyncSession = Depends(get_db)
):
    """Update agent configuration and increment version to trigger a push."""
    config_res = await db.execute(select(AgentConfig).where(AgentConfig.device_id == device_id))
    config = config_res.scalar_one_or_none()
    
    if not config:
        config = AgentConfig(device_id=device_id)
        db.add(config)

    if update.interval is not None:
        config.interval = update.interval
    if update.disk_paths is not None:
        config.disk_paths = update.disk_paths
    if update.enable_temp is not None:
        config.enable_temp = update.enable_temp
        
    # Increment version so the agent knows to update its local config.json
    config.version += 1
    
    await db.commit()
    await db.refresh(config)
    
    return AgentConfigResponse(
        device_id=device_id,
        interval=config.interval,
        disk_paths=config.disk_paths,
        enable_temp=config.enable_temp
    )


@router.get("/overview", response_model=AgentsOverviewResponse)
async def get_agents_overview(db: AsyncSession = Depends(get_db)) -> AgentsOverviewResponse:
    """Get a summary of all agents for the Agents Tab.

    Optimized to use 2 bulk queries instead of N×27 sequential queries.
    Pre-fetches latest metrics and 24-hour hourly counts in one pass each,
    then assembles the response in Python.
    """
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    # 1. Fetch all agent-linked devices in a single JOIN
    res = await db.execute(
        select(Device, AgentToken)
        .join(AgentToken, Device.id == AgentToken.device_id)
    )
    results = res.all()

    if not results:
        return AgentsOverviewResponse(
            agents=[], total_agents=0, active_agents=0,
            total_data_points=0, avg_cpu=0.0, avg_ram=0.0
        )

    device_ids = [d.id for d, _ in results]
    token_map = {d.id: t for d, t in results}
    device_map = {d.id: d for d, _ in results}

    # 2. Bulk-fetch all metrics for all agents in last 24h (single query)
    metrics_res = await db.execute(
        select(DeviceMetrics)
        .where(
            DeviceMetrics.device_id.in_(device_ids),
            DeviceMetrics.timestamp >= cutoff_24h.replace(tzinfo=None)
        )
        .order_by(DeviceMetrics.device_id, DeviceMetrics.timestamp.desc())
    )
    all_24h_metrics = metrics_res.scalars().all()

    # 3. Bulk-count total metrics per device (single query)
    total_count_res = await db.execute(
        select(DeviceMetrics.device_id, func.count(DeviceMetrics.id).label("cnt"))
        .where(DeviceMetrics.device_id.in_(device_ids))
        .group_by(DeviceMetrics.device_id)
    )
    total_count_map: dict[int, int] = {row.device_id: row.cnt for row in total_count_res.all()}

    # Index 24h metrics in Python: {device_id: [metrics...]}
    from collections import defaultdict
    metrics_by_device: dict[int, list] = defaultdict(list)
    for m in all_24h_metrics:
        metrics_by_device[m.device_id].append(m)

    agents_list = []
    total_metrics_count = 0
    total_cpu = 0.0
    total_ram = 0.0
    active_count = 0

    for device_id in device_ids:
        device = device_map[device_id]
        token = token_map[device_id]
        device_metrics_24h = metrics_by_device[device_id]  # already sorted desc
        last_m = device_metrics_24h[0] if device_metrics_24h else None

        m_count = total_count_map.get(device_id, 0)
        total_metrics_count += m_count

        # Active = last heartbeat within 5 minutes
        last_seen = ensure_utc(token.last_seen)
        created_at = ensure_utc(token.created_at)
        is_active = bool(last_seen and (now - last_seen).total_seconds() < 300)
        if is_active:
            active_count += 1

        # Uptime % for last 24h
        time_known = now - (created_at or cutoff_24h)
        relevant_window = min(timedelta(hours=24), time_known)
        window_seconds = max(60, relevant_window.total_seconds())
        expected = window_seconds / 30.0
        day_count = len(device_metrics_24h)
        uptime_pct = min(100.0, (day_count / expected) * 100.0) if expected > 0 else 100.0

        # Hourly uptime history — computed in Python from pre-fetched data (0 extra queries)
        agent_birth = created_at or cutoff_24h
        uptime_history: list[float] = []
        for h in range(24):
            h_start = cutoff_24h + timedelta(hours=h)
            h_end = h_start + timedelta(hours=1)
            if h_start < agent_birth:
                uptime_history.append(100.0)  # unknown period → assume up
                continue
            h_count = sum(1 for m in device_metrics_24h if h_start.replace(tzinfo=None) <= m.timestamp < h_end.replace(tzinfo=None))
            uptime_history.append(min(100.0, (h_count / 120.0) * 100.0))

        if last_m:
            total_cpu += last_m.cpu_percent
            total_ram += last_m.ram_percent

        agents_list.append(AgentSummary(
            device_id=device.id,
            hostname=device.hostname or device.display_name,
            ip=device.ip,
            is_online=is_active,
            agent_version=token.agent_version,
            last_seen=token.last_seen,
            cpu_usage=last_m.cpu_percent if last_m else 0.0,
            ram_usage=last_m.ram_percent if last_m else 0.0,
            temp=last_m.temperature if last_m else None,
            uptime_pct=uptime_pct,
            uptime_history=uptime_history,
            metrics_count=m_count,
            has_pending_token=bool(token.pending_token),
            pending_at=token.pending_at
        ))

    n = len(agents_list)
    return AgentsOverviewResponse(
        agents=agents_list,
        total_agents=n,
        active_agents=active_count,
        total_data_points=total_metrics_count,
        avg_cpu=total_cpu / n if n else 0.0,
        avg_ram=total_ram / n if n else 0.0
    )


@router.get("/global-metrics", response_model=GlobalMetricsResponse)
async def get_global_metrics(db: AsyncSession = Depends(get_db)) -> GlobalMetricsResponse:
    """Get aggregated network-wide performance history for the last 24 hours."""
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    
    # Fetch all metrics for the last 24h
    res = await db.execute(
        select(DeviceMetrics.timestamp, DeviceMetrics.cpu_percent, DeviceMetrics.ram_percent)
        .where(DeviceMetrics.timestamp >= cutoff_24h.replace(tzinfo=None))
        .order_by(DeviceMetrics.timestamp.asc())
    )
    all_metrics = res.all()
    
    # Group by 15-minute intervals in Python
    buckets = {}
    
    for ts, cpu, ram in all_metrics:
        # Bucket: Round down to the nearest 15 minutes
        bucket_ts = ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)
        if bucket_ts not in buckets:
            buckets[bucket_ts] = {"cpu": [], "ram": [], "count": 0}
        
        buckets[bucket_ts]["cpu"].append(cpu)
        buckets[bucket_ts]["ram"].append(ram)
        buckets[bucket_ts]["count"] += 1
        
    history_list = []
    # Ensure we have a sorted list of buckets
    for b_ts in sorted(buckets.keys()):
        b_data = buckets[b_ts]
        history_list.append(GlobalMetricPoint(
            timestamp=b_ts,
            avg_cpu=sum(b_data["cpu"]) / len(b_data["cpu"]) if b_data["cpu"] else 0.0,
            avg_ram=sum(b_data["ram"]) / len(b_data["ram"]) if b_data["ram"] else 0.0,
            data_points=b_data["count"]
        ))
        
    return GlobalMetricsResponse(history=history_list)


# ---------------------------------------------------------------------------
# UI Endpoints (Dashboard -> Server)
# ---------------------------------------------------------------------------

@router.get("/status/{device_id}", response_model=AgentStatusResponse)
async def get_agent_status(device_id: int, db: AsyncSession = Depends(get_db)) -> AgentStatusResponse:
    """Get the current status and latest metrics for a specific agent."""
    # Check Token
    token_res = await db.execute(select(AgentToken).where(AgentToken.device_id == device_id))
    token = token_res.scalar_one_or_none()
    
    if not token:
        return AgentStatusResponse(
            device_id=device_id,
            is_active=False,
            message="No agent linked"
        )

    # Get latest metrics
    metrics_res = await db.execute(
        select(DeviceMetrics)
        .where(DeviceMetrics.device_id == device_id)
        .order_by(desc(DeviceMetrics.timestamp))
        .limit(1)
    )
    last_metrics = metrics_res.scalar_one_or_none()
    
    # Calculate health (Healthy if seen within last 5 minutes)
    is_healthy = False
    last_seen = ensure_utc(token.last_seen)
    if last_seen:
        is_healthy = (datetime.now(timezone.utc) - last_seen).total_seconds() < 300

    return AgentStatusResponse(
        device_id=device_id,
        is_installed=True,
        is_active=token.is_active and is_healthy,
        is_healthy=is_healthy,
        last_seen=token.last_seen,
        agent_version=token.agent_version,
        latest_version=LATEST_AGENT_VERSION,
        latest_metrics=last_metrics.to_dict() if last_metrics else None
    )


@router.get("/metrics/{device_id}", response_model=MetricsHistoryResponse)
async def get_metrics_history(
    device_id: int, 
    limit: int = 60, 
    db: AsyncSession = Depends(get_db)
) -> MetricsHistoryResponse:
    """Get the recent metrics history for a specific device."""
    result = await db.execute(
        select(DeviceMetrics)
        .where(DeviceMetrics.device_id == device_id)
        .order_by(desc(DeviceMetrics.timestamp))
        .limit(limit)
    )
    metrics = result.scalars().all()
    
    # We return them in chronological order for the frontend
    snapshots = [m.to_dict() for m in reversed(list(metrics))]
    
    return MetricsHistoryResponse(
        device_id=device_id,
        snapshots=snapshots
    )


@router.get("/download/agent")
async def download_agent_file():
    from app.services.agent_deployer import AGENT_SCRIPT_PATH
    agent_path = AGENT_SCRIPT_PATH
    
    if not agent_path.exists():
        raise HTTPException(status_code=404, detail="Agent script not found on server")
        
    return FileResponse(
        path=str(agent_path), 
        media_type="text/x-python",
        filename="gravitylan-agent.py"
    )


@router.get("/download/config/{device_id}")
async def download_agent_config(device_id: int, db: AsyncSession = Depends(get_db)):
    """Generate and download the agent.conf for a specific device."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
        
    # Get or create token
    token_res = await db.execute(select(AgentToken).where(AgentToken.device_id == device_id))
    token_obj = token_res.scalar_one_or_none()
    if not token_obj:
        import secrets
        token = secrets.token_hex(32)
        token_obj = AgentToken(device_id=device_id, token=token, is_active=True)
        db.add(token_obj)
        await db.commit()
    else:
        token = token_obj.token

    # Detect Server URL (same logic as in deploy)
    from app.models.setting import Setting
    res = await db.execute(select(Setting).where(Setting.key == "server.url"))
    setting = res.scalar_one_or_none()
    server_url = setting.value if setting and setting.value else None
    
    if not server_url:
        from app.scanner.utils import get_local_subnets
        subnets = get_local_subnets()
        if subnets:
            def ip_priority(s):
                ip = s.ip_address
                iface = s.interface_name.lower()
                score = 0
                if any(x in iface for x in ["eth", "eno", "ens", "enp", "wlan", "wlp"]): score += 100
                if ip.startswith("192.168."): score += 50
                if any(x in iface for x in ["docker", "br-", "veth"]): score -= 100
                return score
            best = max(subnets, key=ip_priority)
            port = settings.port
            server_url = f"http://{best.ip_address}:{port}" if port != 80 else f"http://{best.ip_address}"
        else:
            port = settings.port
            server_url = f"http://localhost:{port}" if port != 80 else "http://localhost"

    # Generate JSON config
    config_data = {
        "server_url": server_url,
        "token": token,
        "device_id": device_id,
        "interval": 30
    }
    return PlainTextResponse(json.dumps(config_data, indent=2))


@router.get("/download/install-sh/{device_id}")
async def download_install_script(device_id: int, db: AsyncSession = Depends(get_db)):
    """Generate a shell script for easy 'curl | bash' installation."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Detect Server URL
    from app.models.setting import Setting
    res = await db.execute(select(Setting).where(Setting.key == "server.url"))
    setting = res.scalar_one_or_none()
    server_url = setting.value if setting and setting.value else None
    
    if not server_url:
        from app.scanner.utils import get_local_subnets
        subnets = get_local_subnets()
        if subnets:
            def ip_priority(s):
                ip = s.ip_address
                iface = s.interface_name.lower()
                score = 0
                if any(x in iface for x in ["eth", "eno", "ens", "enp", "wlan", "wlp"]): score += 100
                if ip.startswith("192.168."): score += 50
                return score
            best = max(subnets, key=ip_priority)
            port = settings.port
            server_url = f"http://{best.ip_address}:{port}" if port != 80 else f"http://{best.ip_address}"
        else:
            port = settings.port
            server_url = f"http://localhost:{port}" if port != 80 else "http://localhost"

    script = f"""#!/bin/bash
set -e
echo "--- GravityLAN Agent Installer ---"

INSTALL_DIR="/opt/gravitylan-agent"
SERVER_URL="{server_url}"
DEVICE_ID="{device_id}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Error: This script must be run as root to install the agent."
  echo "Please run the command with sudo bash:"
  echo "curl -sSL $SERVER_URL/api/agent/download/install-sh/$DEVICE_ID | sudo bash"
  exit 1
fi

echo "1. Cleaning up old versions..."
systemctl stop gravitylan-agent.service 2>/dev/null || true
pkill -9 -f gravitylan-agent.py 2>/dev/null || true
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

echo "2. Downloading agent and config..."
curl -sSL "$SERVER_URL/api/agent/download/agent" -o "$INSTALL_DIR/gravitylan-agent.py"
curl -sSL "$SERVER_URL/api/agent/download/config/$DEVICE_ID" -o "$INSTALL_DIR/agent.conf"

echo "3. Setting up systemd service..."
PYTHON_BIN=$(which python3 || which python)
cat > /etc/systemd/system/gravitylan-agent.service <<EOF
[Unit]
Description=GravityLAN System Monitor Agent
After=network-online.target

[Service]
Type=simple
ExecStart=$PYTHON_BIN $INSTALL_DIR/gravitylan-agent.py
WorkingDirectory=$INSTALL_DIR
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable gravitylan-agent
systemctl restart gravitylan-agent

echo "--- Installation Complete ---"
systemctl status gravitylan-agent --no-pager
"""
    return PlainTextResponse(script)


@router.post("/deploy/{device_id}", response_model=AgentDeployResponse)
async def deploy_agent_endpoint(
    device_id: int,
    request: AgentDeployRequest,
    db: AsyncSession = Depends(get_db)
) -> AgentDeployResponse:
    """
    Deploy the GravityLAN Agent to a remote device via SSH.
    
    This triggers the SSH-based deployment process. Credentials are used 
    exclusively for this request and are never stored in the database.
    """
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # 1. Determine Server URL
    # Strategy: Check settings first, then fall back to detecting local IP
    from app.models.setting import Setting
    res = await db.execute(select(Setting).where(Setting.key == "server.url"))
    setting = res.scalar_one_or_none()
    
    server_url = setting.value if setting and setting.value else None
    
    if not server_url:
        # Auto-detect local IP of this server
        from app.scanner.utils import get_local_subnets
        subnets = get_local_subnets()
        if subnets:
            # Sorter: Prioritize 192.168.x.x and 10.x.x.x, avoid 172.x.x.x (Docker) and bridge names
            def ip_priority(s):
                ip = s.ip_address
                iface = s.interface_name.lower()
                score = 0
                if any(x in iface for x in ["eth", "eno", "ens", "enp", "wlan", "wlp"]): score += 100
                if ip.startswith("192.168."): score += 50
                if ip.startswith("10."): score += 40
                if any(x in iface for x in ["docker", "br-", "veth", "tailscale", "tun"]): score -= 100
                return score

            best_subnet = max(subnets, key=ip_priority)
            local_ip = best_subnet.ip_address
            port = settings.port
            server_url = f"http://{local_ip}:{port}" if port != 80 else f"http://{local_ip}"
            logger.info("Auto-detected server URL: %s (via %s)", server_url, best_subnet.interface_name)
        else:
            port = settings.port
            server_url = f"http://localhost:{port}" if port != 80 else "http://localhost"
            logger.warning("Could not detect local IP, falling back to localhost for Agent URL")

    # 2. Run Deployment
    logger.info("Starting agent deployment for device %d (%s) to server %s", 
                device_id, device.ip, server_url)
    
    success, message, token = await deploy_agent(
        host_ip=device.ip,
        ssh_user=request.ssh_user,
        ssh_password=request.ssh_password,
        ssh_key=request.ssh_key,
        ssh_port=request.ssh_port,
        server_url=server_url,
        device_id=device_id
    )

    if success:
        # Save or update the token in the database
        # We delete any old tokens first to ensure a clean start
        await db.execute(delete(AgentToken).where(AgentToken.device_id == device_id))
        
        new_token = AgentToken(
            device_id=device_id,
            token=token,
            is_active=True,
            last_seen=None
        )
        db.add(new_token)
        
        # Ensure we have a default config for the agent
        config_res = await db.execute(select(AgentConfig).where(AgentConfig.device_id == device_id))
        if not config_res.scalar_one_or_none():
            db.add(AgentConfig(device_id=device_id))
            
        await db.commit()
        return AgentDeployResponse(status="success", message=message)
    else:
        return AgentDeployResponse(status="failed", message=message)


@router.post("/uninstall/{device_id}")
async def uninstall_agent_endpoint(
    device_id: int,
    request: AgentDeployRequest,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Uninstall the GravityLAN Agent from a remote device.
    """
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    success, message = await remove_agent(
        host_ip=device.ip,
        ssh_user=request.ssh_user,
        ssh_password=request.ssh_password,
        ssh_key=request.ssh_key,
        ssh_port=request.ssh_port
    )

    if success:
        # Deactivate token in DB
        await db.execute(
            delete(AgentToken).where(AgentToken.device_id == device_id)
        )
        await db.commit()
        return {"status": "success", "message": message}
    else:
        return {"status": "failed", "message": message}


@router.websocket("/ws/{device_id}")
async def agent_websocket(websocket: WebSocket, device_id: int):
    """WebSocket for real-time metric streaming to the dashboard with authentication."""
    from app.api.auth import authenticate_websocket
    
    auth_info = await authenticate_websocket(websocket, endpoint_type="agent", device_id=device_id)
    if not auth_info.get("authenticated"):
        return

    # Agent websocket is restricted to browser-sessions, legacy master cookie, or agent-specific tokens
    if auth_info.get("auth_type") not in ("session", "master_legacy", "agent"):
        await websocket.close(code=4003, reason="Unauthorized access level")
        return

    await websocket.accept()
    if device_id not in _ws_subscribers:
        _ws_subscribers[device_id] = set()
    _ws_subscribers[device_id].add(websocket)
    
    try:
        if device_id in _latest_metrics:
            await websocket.send_json({"type": "metrics", "data": _latest_metrics[device_id]})
            
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if device_id in _ws_subscribers:
            _ws_subscribers[device_id].discard(websocket)


@router.get("/download/uninstall-sh/{device_id}")
async def download_uninstall_script(device_id: int, db: AsyncSession = Depends(get_db)):
    """Generate a shell script for easy 'curl | bash' uninstallation."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    script = f"""#!/bin/bash
echo "--- GravityLAN Agent Uninstaller ---"

INSTALL_DIR="/opt/gravitylan-agent"

if [ "$(id -u)" -ne 0 ]; then
  echo "Error: This script must be run as root to uninstall the agent."
  echo "Please run the command with sudo bash (e.g. curl -sSL ... | sudo bash)"
  exit 1
fi

echo "1. Stopping and disabling service..."
systemctl stop gravitylan-agent.service 2>/dev/null || true
systemctl disable gravitylan-agent.service 2>/dev/null || true

echo "2. Removing files..."
rm -f /etc/systemd/system/gravitylan-agent.service
rm -rf "$INSTALL_DIR"

echo "3. Reloading systemd..."
systemctl daemon-reload

echo "--- Uninstallation Complete ---"
"""
    return PlainTextResponse(script)
    
@router.post("/adopt/{device_id}")
async def adopt_agent_token(device_id: int, db: AsyncSession = Depends(get_db), current_user: str = Depends(get_current_admin)):
    """Manually adopt a pending token for a device."""
    token_res = await db.execute(select(AgentToken).where(AgentToken.device_id == device_id))
    token_obj = token_res.scalar_one_or_none()
    
    if not token_obj or not token_obj.pending_token:
        raise HTTPException(status_code=400, detail="No pending token found for this device")
    
    # Move pending token to active token
    old_token = token_obj.token
    token_obj.token = token_obj.pending_token
    token_obj.pending_token = None
    token_obj.pending_at = None
    token_obj.is_active = True
    
    await db.commit()
    logger.info("Device %d adopted new token (Replaced %s... with %s...)", 
                device_id, old_token[:8], token_obj.token[:8])
    
    return {"status": "ok", "message": "Token adopted successfully"}
