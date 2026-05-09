from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class TopologyLinkBase(BaseModel):
    source_id: int
    target_id: int
    link_type: str = "1GbE"
    speed: Optional[int] = None
    color: Optional[str] = None
    notes: Optional[str] = None

class TopologyLinkCreate(TopologyLinkBase):
    pass

class TopologyLink(TopologyLinkBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class RackBase(BaseModel):
    name: str
    units: int = 42
    width: int = 19
    notes: Optional[str] = None

class RackCreate(RackBase):
    pass

class Rack(RackBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class RackWithDevices(Rack):
    devices: List[dict] # We'll use dict for now to avoid circular issues or complex nested schemas

    class Config:
        from_attributes = True
