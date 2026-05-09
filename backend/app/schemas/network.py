"""Pydantic schemas for network subnet management."""

from pydantic import BaseModel, Field


class SubnetBase(BaseModel):
    cidr: str = Field(..., description="Subnet in CIDR notation (e.g. 192.168.100.0/24)")
    name: str = Field(..., description="Human-readable name for the subnet")
    dns_server: str | None = Field(None, description="Optional specific DNS server to use for this subnet")
    is_enabled: bool = True


class SubnetCreate(SubnetBase):
    pass


class SubnetUpdate(BaseModel):
    cidr: str | None = None
    name: str | None = None
    dns_server: str | None = None
    is_enabled: bool | None = None


class SubnetResponse(SubnetBase):
    id: int

    class Config:
        from_attributes = True
