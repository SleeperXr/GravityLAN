"""API router for network subnet management."""

import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.network import Subnet
from sqlalchemy import delete
import ipaddress
from app.schemas.network import SubnetCreate, SubnetResponse, SubnetUpdate

logger = logging.getLogger(__name__)
from app.api.auth import get_current_admin

router = APIRouter(prefix="/api/network", tags=["network"])


async def cleanup_invalid_subnets():
    """Remove subnets that are not valid IP networks."""
    async with async_session() as session:
        try:
            result = await session.execute(select(Subnet))
            subnets = result.scalars().all()
            for sub in subnets:
                try:
                    ipaddress.ip_network(sub.cidr, strict=False)
                except ValueError:
                    logger.warning(f"Removing invalid subnet from database: {sub.cidr}")
                    await session.execute(delete(Subnet).where(Subnet.id == sub.id))
            await session.commit()
        except Exception as e:
            logger.error(f"Failed to cleanup invalid subnets: {e}")

@router.on_event("startup")
async def on_startup():
    await cleanup_invalid_subnets()

async def get_db():
    async with async_session() as session:
        yield session


@router.get("/subnets", response_model=list[SubnetResponse], dependencies=[Depends(get_current_admin)])
async def get_subnets(db: AsyncSession = Depends(get_db)):
    """Get all configured subnets."""
    result = await db.execute(select(Subnet).order_by(Subnet.name))
    return result.scalars().all()


@router.post("/subnets", response_model=SubnetResponse, dependencies=[Depends(get_current_admin)])
async def create_subnet(subnet_in: SubnetCreate, db: AsyncSession = Depends(get_db)):
    """Create a new subnet configuration."""
    subnet = Subnet(**subnet_in.model_dump())
    db.add(subnet)
    await db.commit()
    await db.refresh(subnet)
    return subnet


@router.patch("/subnets/{subnet_id}", response_model=SubnetResponse, dependencies=[Depends(get_current_admin)])
async def update_subnet(subnet_id: int, subnet_in: SubnetUpdate, db: AsyncSession = Depends(get_db)):
    """Update a subnet configuration."""
    subnet = await db.get(Subnet, subnet_id)
    if not subnet:
        raise HTTPException(status_code=404, detail="Subnet not found")
    
    update_data = subnet_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(subnet, field, value)
    
    await db.commit()
    await db.refresh(subnet)
    return subnet


@router.delete("/subnets/{subnet_id}", dependencies=[Depends(get_current_admin)])
async def delete_subnet(subnet_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a subnet configuration."""
    subnet = await db.get(Subnet, subnet_id)
    if not subnet:
        raise HTTPException(status_code=404, detail="Subnet not found")
    
    await db.delete(subnet)
    await db.commit()
    return {"status": "ok"}
