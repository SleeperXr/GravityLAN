"""Pydantic schemas for the Summary API."""

from datetime import datetime
from pydantic import BaseModel

class DeviceSummary(BaseModel):
    total: int
    online: int
    offline: int

class AgentSummaryInfo(BaseModel):
    total: int
    active: int
    avg_cpu: float
    avg_ram: float

class ScannerSummary(BaseModel):
    status: str
    last_scan: datetime | None

class ActiveIssue(BaseModel):
    type: str  # "agent_offline" | "service_down"
    severity: str  # "error" | "warning" | "info"
    device_id: int
    device_name: str
    details: str

class SummaryResponse(BaseModel):
    devices: DeviceSummary
    agents: AgentSummaryInfo
    scanner: ScannerSummary
    active_issues: list[ActiveIssue]
