"""Pydantic schemas for unified health summary API responses."""

from datetime import datetime
from pydantic import BaseModel

class HealthDevicesSummary(BaseModel):
    total: int
    online: int
    offline: int

class HealthAgentsSummary(BaseModel):
    total: int
    high_cpu: int
    high_temp: int
    offline_agents: int

class HealthIssuesSummary(BaseModel):
    active: int
    by_type: dict[str, int]

class HealthNotificationsSummary(BaseModel):
    unread: int
    fresh_30min: int

class HealthScannerSummary(BaseModel):
    running: bool
    last_run: datetime | None
    stale_hours: float | None

class HealthSummaryResponse(BaseModel):
    api_version: str
    devices: HealthDevicesSummary
    agents: HealthAgentsSummary
    issues: HealthIssuesSummary
    notifications: HealthNotificationsSummary
    scanner: HealthScannerSummary
