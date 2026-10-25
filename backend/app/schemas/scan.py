"""Pydantic schemas for network scan operations."""

from datetime import datetime
from enum import Enum

from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from app.schemas.network import MIN_SCAN_PREFIX, validate_scan_cidr

# Most subnets one scan request may name (the setup wizard caps its list the same way)
MAX_SCAN_SUBNETS = 64


class ScanStatus(str, Enum):
    """Possible states of a scan job."""

    IDLE = "idle"
    RUNNING = "running"
    DISCOVERING = "discovering"
    IDENTIFYING = "identifying"
    DEVICES_UPDATED = "devices_updated"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SubnetInfo(BaseModel):
    """Information about a discovered network interface/subnet."""

    interface_name: str
    ip_address: str
    subnet: str
    netmask: str
    is_up: bool = True
    is_virtual: bool = False


class ScanRequest(BaseModel):
    """Request to start a network scan."""

    subnets: list[str] = Field(
        default_factory=list,
        max_length=MAX_SCAN_SUBNETS,
        description=(
            f"IPv4 CIDR subnets to scan, each /{MIN_SCAN_PREFIX} or smaller; "
            "empty means the enabled subnets of the network overview"
        ),
    )
    ports: list[Annotated[int, Field(ge=1, le=65535)]] | None = Field(None, max_length=1024)

    @field_validator("subnets")
    @classmethod
    def validate_subnets(cls, v: list[str]) -> list[str]:
        # Same rules as the subnet management (#43): a 0.0.0.0/0 sweep would build a host
        # list of four billion addresses and stall the event loop
        return list(dict.fromkeys(validate_scan_cidr(cidr) for cidr in v))


class ScanProgress(BaseModel):
    """Real-time scan progress update sent via WebSocket."""

    status: ScanStatus
    current_subnet: str = ""
    hosts_scanned: int = 0
    hosts_total: int = 0
    devices_found: int = 0
    message: str = ""
    progress: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.now)


class DiscoveredDevice(BaseModel):
    """A device discovered during a network scan (pre-DB)."""

    ip: str
    hostname: str | None = None
    mac: str | None = None
    ports: list[int] = []
    device_type: str = "unknown"
    device_subtype: str = "Unknown"
    services: list[dict] = []


class ScanProfileResponse(BaseModel):
    """Configuration profile for network scanning."""

    id: int
    name: str
    description: str
    nmap_arguments: str
    is_default: bool

