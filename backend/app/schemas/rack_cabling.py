"""Request and response shapes for rack equipment, ports and rack cabling."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RackItemKind = Literal[
    "switch_unmanaged",
    "ups",
    "patch_copper",
    "patch_fiber",
    "phone_system",
    "blank",
    "cable_management",
    "other",
]
PortOwnerType = Literal["device", "item"]
HEX_COLOUR = r"^#[0-9a-fA-F]{6}$"


class RackItemIn(BaseModel):
    rack_id: int
    name: str = Field(min_length=1, max_length=100)
    kind: RackItemKind = "other"
    rack_unit: int | None = Field(default=None, ge=1, le=100)
    rack_height: int = Field(default=1, ge=1, le=10)
    notes: str | None = Field(default=None, max_length=2000)
    port_count: int = Field(default=0, ge=0, le=96)
    port_kind: str = Field(default="RJ45", min_length=1, max_length=20)


class RackItemPatch(BaseModel):
    rack_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    kind: RackItemKind | None = None
    rack_unit: int | None = Field(default=None, ge=1, le=100)
    rack_height: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = Field(default=None, max_length=2000)


class RackItemOut(BaseModel):
    id: int
    rack_id: int
    name: str
    kind: str
    rack_unit: int | None
    rack_height: int
    notes: str | None

    model_config = {"from_attributes": True}


class PortsIn(BaseModel):
    owner_type: PortOwnerType
    owner_id: int
    count: int = Field(ge=0, le=96)
    kind: str = Field(default="RJ45", min_length=1, max_length=20)


class PortOut(BaseModel):
    id: int
    device_id: int | None
    rack_item_id: int | None
    number: int
    kind: str

    model_config = {"from_attributes": True}


class CableIn(BaseModel):
    a_port_id: int
    b_port_id: int
    cable: str = Field(default="Cat6", min_length=1, max_length=40)
    color: str | None = Field(default=None, pattern=HEX_COLOUR)
    notes: str | None = Field(default=None, max_length=2000)


class CablePatch(BaseModel):
    cable: str | None = Field(default=None, min_length=1, max_length=40)
    color: str | None = Field(default=None, pattern=HEX_COLOUR)
    notes: str | None = Field(default=None, max_length=2000)


class CableOut(BaseModel):
    id: int
    a_port_id: int
    b_port_id: int
    cable: str
    color: str | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CablingOut(BaseModel):
    items: list[RackItemOut]
    ports: list[PortOut]
    cables: list[CableOut]
