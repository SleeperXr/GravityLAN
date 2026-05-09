from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List

from app.database import get_db
from app.models.topology import Rack as RackModel, TopologyLink as LinkModel
from app.schemas.topology import Rack as RackSchema, RackCreate, TopologyLink as LinkSchema, TopologyLinkCreate

router = APIRouter(prefix="/topology", tags=["topology"])

# --- Rack Endpoints ---

@router.get("/racks", response_model=List[RackSchema])
async def get_racks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RackModel))
    return result.scalars().all()

@router.post("/racks", response_model=RackSchema)
async def create_rack(rack: RackCreate, db: AsyncSession = Depends(get_db)):
    db_rack = RackModel(**rack.model_dump())
    db.add(db_rack)
    await db.commit()
    await db.refresh(db_rack)
    return db_rack

@router.delete("/racks/{rack_id}")
async def delete_rack(rack_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(RackModel).where(RackModel.id == rack_id))
    await db.commit()
    return {"message": "Rack deleted"}

# --- Link Endpoints ---

@router.get("/links", response_model=List[LinkSchema])
async def get_links(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LinkModel))
    return result.scalars().all()

@router.post("/links", response_model=LinkSchema)
async def create_link(link: TopologyLinkCreate, db: AsyncSession = Depends(get_db)):
    # Prevent duplicate links between same devices if needed, but for now just allow
    db_link = LinkModel(**link.model_dump())
    db.add(db_link)
    await db.commit()
    await db.refresh(db_link)
    return db_link

@router.delete("/links/{link_id}")
async def delete_link(link_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(LinkModel).where(LinkModel.id == link_id))
    await db.commit()
    return {"message": "Link deleted"}
