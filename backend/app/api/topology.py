from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_, and_
from sqlalchemy.exc import IntegrityError
from typing import List

from app.api.policy import policy
from app.database import get_db
from app.models.topology import Rack as RackModel, TopologyLink as LinkModel
from app.models.device import Device as DeviceModel
from app.models.rack_cabling import RackItem as RackItemModel
from app.schemas.topology import Rack as RackSchema, RackCreate, TopologyLink as LinkSchema, TopologyLinkCreate, TopologyLinkUpdate, RackPatch
from app.services.cache_service import topology_cache

# Auth on the router itself (defense in depth); main.py adds it again on include.
router = APIRouter(prefix="/api/topology", tags=["topology"])

@router.get("/map", dependencies=[policy(scope="topology:read")])
async def get_topology_map(db: AsyncSession = Depends(get_db)):
    """Unified endpoint for the topology map, backed by in-memory cache."""
    if not topology_cache.is_stale():
        cached = topology_cache.get_all()
        if cached: return cached

    # Cache miss: Fetch everything
    devices_res = await db.execute(select(DeviceModel))
    links_res = await db.execute(select(LinkModel))
    racks_res = await db.execute(select(RackModel))
    
    # Simple conversion to dict for JSON serialization
    # In a real app, we'd use schemas, but for the cache dict is fine
    from app.schemas.device import DeviceResponse as DeviceSchema
    from app.schemas.topology import Rack as RackSchema, TopologyLink as LinkSchema
    
    devices = [DeviceSchema.model_validate(d).model_dump() for d in devices_res.scalars().all()]
    links = [LinkSchema.model_validate(l).model_dump() for l in links_res.scalars().all()]
    racks = [RackSchema.model_validate(r).model_dump() for r in racks_res.scalars().all()]
    
    topology_cache.set_data(devices, links, racks)
    return topology_cache.get_all()

# --- Rack Endpoints ---

@router.get("/racks", response_model=List[RackSchema], dependencies=[policy(scope="topology:read")])
async def get_racks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RackModel))
    return result.scalars().all()

@router.post("/racks", response_model=RackSchema, dependencies=[policy(scope="topology:write")])
async def create_rack(rack: RackCreate, db: AsyncSession = Depends(get_db)):
    db_rack = RackModel(**rack.model_dump())
    db.add(db_rack)
    await db.commit()
    topology_cache.invalidate()
    await db.refresh(db_rack)
    return db_rack

@router.patch("/racks/{rack_id}", response_model=RackSchema, dependencies=[policy(scope="topology:write")])
async def update_rack(rack_id: int, patch: RackPatch, db: AsyncSession = Depends(get_db)):
    """Rename a rack or change its height (units) and width; refused while something in it would not fit."""
    rack = await db.get(RackModel, rack_id)
    if rack is None:
        raise HTTPException(status_code=404, detail="Rack not found")
    values = patch.model_dump(exclude_unset=True)
    if any(field in values and values[field] is None for field in ("name", "units", "width")):
        raise HTTPException(status_code=422, detail="This field cannot be cleared")
    units = values.get("units", rack.units)
    devices = (await db.execute(select(DeviceModel).where(DeviceModel.rack_id == rack_id, DeviceModel.rack_unit.is_not(None)))).scalars().all()
    items = (await db.execute(select(RackItemModel).where(RackItemModel.rack_id == rack_id, RackItemModel.rack_unit.is_not(None)))).scalars().all()
    placed = [(d.display_name or d.ip, d.rack_unit, d.rack_height or 1) for d in devices]
    placed += [(i.name, i.rack_unit, i.rack_height or 1) for i in items]
    for name, unit, height in placed:
        if unit > units or unit - height + 1 < 1:
            raise HTTPException(status_code=409, detail=f"{name} sits on unit {unit}; move it before making the rack smaller")
    for field, value in values.items():
        setattr(rack, field, value)
    await db.commit()
    topology_cache.invalidate()
    await db.refresh(rack)
    return rack

@router.delete("/racks/{rack_id}", dependencies=[policy(scope="topology:write")])
async def delete_rack(rack_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(RackModel).where(RackModel.id == rack_id))
    await db.commit()
    topology_cache.invalidate()
    return {"message": "Rack deleted"}

# --- Link Endpoints ---

@router.get("/links", response_model=List[LinkSchema], dependencies=[policy(scope="topology:read")])
async def get_links(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LinkModel))
    return result.scalars().all()

@router.post("/links", response_model=LinkSchema, dependencies=[policy(scope="topology:write")])
async def create_link(link: TopologyLinkCreate, db: AsyncSession = Depends(get_db)):
    """Link two devices. A link is undirected: one already there in either direction is a 409, never a second row."""
    if link.source_id == link.target_id:
        raise HTTPException(status_code=422, detail="A device cannot be linked to itself")
    existing = (await db.execute(select(LinkModel.id).where(or_(
        and_(LinkModel.source_id == link.source_id, LinkModel.target_id == link.target_id),
        and_(LinkModel.source_id == link.target_id, LinkModel.target_id == link.source_id),
    )).limit(1))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"These devices are already linked (link {existing})")
    db_link = LinkModel(**link.model_dump())
    db.add(db_link)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent request created the same link first (or a device is gone)
        await db.rollback()
        raise HTTPException(status_code=409, detail="These devices are already linked")
    topology_cache.invalidate()
    await db.refresh(db_link)
    return db_link

@router.patch("/links/{link_id}", response_model=LinkSchema, dependencies=[policy(scope="topology:write")])
async def update_link(link_id: int, link_update: TopologyLinkUpdate, db: AsyncSession = Depends(get_db)):
    # TopologyLinkUpdate allows partial updates
    db_link = await db.get(LinkModel, link_id)
    if not db_link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    update_data = link_update.model_dump(exclude_unset=True)
    if update_data.get("role", "") is None:
        del update_data["role"]  # the role is never empty; null means "leave it"
    for field, value in update_data.items():
        setattr(db_link, field, value)
    
    await db.commit()
    topology_cache.invalidate()
    await db.refresh(db_link)
    return db_link

@router.delete("/links/{link_id}", dependencies=[policy(scope="topology:write")])
async def delete_link(link_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(LinkModel).where(LinkModel.id == link_id))
    await db.commit()
    topology_cache.invalidate()
    return {"message": "Link deleted"}

@router.get("/nodes", dependencies=[policy(scope="topology:read")])
async def get_topology_nodes(db: AsyncSession = Depends(get_db)):
    """Fetch all nodes (devices) from the topology map."""
    map_data = await get_topology_map(db)
    return map_data["devices"]

@router.get("/edges", dependencies=[policy(scope="topology:read")])
async def get_topology_edges(db: AsyncSession = Depends(get_db)):
    """Fetch all edges (links) from the topology map."""
    map_data = await get_topology_map(db)
    return map_data["links"]
