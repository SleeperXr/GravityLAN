"""Agents listing API endpoint for GravityLAN."""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.auth import get_current_admin
from app.api.agent import get_agents_overview, get_agent_status
from app.schemas.agent import AgentsOverviewResponse, AgentStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agent"])

@router.get("", response_model=AgentsOverviewResponse)
async def list_agents(
    db: AsyncSession = Depends(get_db),
    current_admin: str = Depends(get_current_admin)
) -> AgentsOverviewResponse:
    """Retrieve overview of all active agents with system metrics."""
    return await get_agents_overview(db, current_admin)

@router.get("/{device_id}", response_model=AgentStatusResponse)
async def get_agent_details(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: str = Depends(get_current_admin)
) -> AgentStatusResponse:
    """Retrieve status and latest metrics for a single agent."""
    return await get_agent_status(device_id, db, current_admin)
