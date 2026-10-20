"""Pydantic schemas for importing subnets/VLANs from a router."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.network import check_gateway_in_subnet, normalize_gateway_ip, validate_scan_cidr

ProviderKey = Literal["snmp", "unifi"]


class RouterImportRequest(BaseModel):
    """Ask a router for its networks. Empty secrets fall back to the stored ones of the same router."""

    provider: ProviderKey
    host: str = Field(..., min_length=1, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    options: dict[str, str | None] = Field(default_factory=dict, max_length=10)
    secrets: dict[str, str] = Field(default_factory=dict, max_length=10)
    # Store host, options and (encrypted) secrets after a successful fetch
    remember: bool = True

    @field_validator("options", "secrets")
    @classmethod
    def limit_values(cls, v: dict) -> dict:
        for key, value in v.items():
            if len(key) > 40 or (value is not None and len(value) > 512):
                raise ValueError("Option or secret too long")
        return v


class RouterSourceResponse(BaseModel):
    """A saved router connection; secrets are never returned, only which ones are stored."""

    provider: ProviderKey
    host: str
    port: int | None = None
    options: dict[str, str | None] = Field(default_factory=dict)
    stored_secrets: list[str] = Field(default_factory=list)


class RouterNetworkPreview(BaseModel):
    cidr: str
    name: str | None = None
    gateway_ip: str | None = None
    vlan_id: int | None = None
    interface: str | None = None
    # new: not configured yet; update: configured, gateway/VLAN would be filled in;
    # exists: configured and nothing to add; too_large: bigger than a /16, cannot be scanned
    status: Literal["new", "update", "exists", "too_large"]
    fills: list[Literal["gateway_ip", "vlan_id"]] = Field(default_factory=list)
    existing_name: str | None = None


class RouterImportPreview(BaseModel):
    # confirm_certificate: the console's TLS certificate must be confirmed (fingerprint) first
    status: Literal["ok", "confirm_certificate"]
    provider: ProviderKey
    host: str
    networks: list[RouterNetworkPreview] = Field(default_factory=list)
    fingerprint: str | None = None
    reason: str | None = None
    message: str | None = None


class RouterImportApplyItem(BaseModel):
    cidr: str
    name: str | None = Field(None, max_length=100)
    gateway_ip: str | None = None
    vlan_id: int | None = Field(None, ge=1, le=4094)

    @field_validator("cidr")
    @classmethod
    def validate_cidr(cls, v: str) -> str:
        return validate_scan_cidr(v)

    @field_validator("gateway_ip")
    @classmethod
    def validate_gateway_ip(cls, v: str | None) -> str | None:
        return normalize_gateway_ip(v)

    @model_validator(mode="after")
    def gateway_inside(self) -> "RouterImportApplyItem":
        check_gateway_in_subnet(self.gateway_ip, self.cidr)
        return self


class RouterImportApply(BaseModel):
    networks: list[RouterImportApplyItem] = Field(..., min_length=1, max_length=256)


class RouterImportApplyResult(BaseModel):
    added: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
