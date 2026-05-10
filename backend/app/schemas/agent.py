"""Pydantic schemas for agent-related API requests and responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Agent Report (incoming from agent)
# ---------------------------------------------------------------------------

class AgentRamReport(BaseModel):
    """RAM metrics as reported by the agent."""

    total_mb: int
    used_mb: int
    percent: float


class AgentDiskReport(BaseModel):
    """Single disk mount metrics as reported by the agent."""

    path: str
    total_gb: float
    used_gb: float
    percent: float


class AgentReportPayload(BaseModel):
    """Full metrics payload received from an agent.

    This is the JSON body the agent POSTs to /api/agent/report.
    """

    device_id: int | None = None
    agent_version: str
    timestamp: float
    cpu_percent: float = Field(ge=0.0, le=100.0)
    ram: AgentRamReport
    disk: list[AgentDiskReport] = []
    temperature: float | None = None
    network: dict[str, dict[str, int]] = {}
    system: dict[str, str] = {}


# ---------------------------------------------------------------------------
# API Responses
# ---------------------------------------------------------------------------

class AgentReportResponse(BaseModel):
    """Response sent back to the agent after a successful report.

    Contains an optional config block to push settings updates.
    Also includes the current device_id to help agents re-sync after a server reset.
    """

    status: str = "ok"
    config: dict | None = None
    config_version: int = 0
    device_id: int | None = None


class AgentStatusResponse(BaseModel):
    """Status of an agent deployment for a specific device."""

    device_id: int
    is_installed: bool = False
    is_active: bool = False
    is_healthy: bool = False
    agent_version: str | None = None
    latest_version: str | None = None
    last_seen: datetime | None = None
    latest_metrics: dict | None = None
    message: str | None = None


class MetricsSnapshot(BaseModel):
    """Single point-in-time metrics snapshot for API responses."""

    cpu_percent: float
    ram: AgentRamReport
    disk: list[AgentDiskReport] = []
    temperature: float | None = None
    network: dict[str, dict[str, int]] = {}
    timestamp: datetime

    model_config = {"from_attributes": True}


class MetricsHistoryResponse(BaseModel):
    """Collection of recent metrics snapshots for chart rendering."""

    device_id: int
    snapshots: list[MetricsSnapshot] = []


# ---------------------------------------------------------------------------
# SSH Deployment
# ---------------------------------------------------------------------------

class AgentDeployRequest(BaseModel):
    """SSH credentials for one-time agent deployment.

    These credentials are used once to install the agent and then
    immediately discarded — never stored in any database.
    """

    ssh_user: str = Field(..., min_length=1, max_length=50)
    ssh_password: str | None = Field(None, min_length=1)
    ssh_key: str | None = None
    ssh_port: int = Field(22, ge=1, le=65535)


class AgentDeployResponse(BaseModel):
    """Result of an agent deployment attempt."""

    status: str  # "success", "failed"
    message: str
    agent_version: str | None = None


# ---------------------------------------------------------------------------
# Agent Configuration (editable from UI)
# ---------------------------------------------------------------------------

class AgentConfigUpdate(BaseModel):
    """Schema for updating agent configuration from the Device Manager."""

    interval: int | None = Field(None, ge=5, le=300)
    disk_paths: list[str] | None = None
    enable_temp: bool | None = None


class AgentConfigResponse(BaseModel):
    """Current agent configuration for a device."""

    device_id: int
    interval: int = 30
    disk_paths: list[str] = ["/"]
    enable_temp: bool = True

# ---------------------------------------------------------------------------
# Agents Overview (for Agents Tab)
# ---------------------------------------------------------------------------

class AgentSummary(BaseModel):
    """Detailed summary for the Agents Tab list."""
    device_id: int
    hostname: str
    ip: str
    is_online: bool
    agent_version: str | None = None
    last_seen: datetime | None = None
    cpu_usage: float = 0.0
    ram_usage: float = 0.0
    temp: float | None = None
    uptime_pct: float = 100.0
    uptime_history: list[float] = []
    metrics_count: int = 0

class AgentsOverviewResponse(BaseModel):
    """Aggregation of all agents and global stats."""
    agents: list[AgentSummary]
    total_agents: int
    active_agents: int
    total_data_points: int
    avg_cpu: float
    avg_ram: float

# ---------------------------------------------------------------------------
# Global Metrics History
# ---------------------------------------------------------------------------

class GlobalMetricPoint(BaseModel):
    """Network-wide average for a specific point in time."""
    timestamp: datetime
    avg_cpu: float
    avg_ram: float
    data_points: int

class GlobalMetricsResponse(BaseModel):
    """History of global performance across the last 24 hours."""
    history: list[GlobalMetricPoint]
