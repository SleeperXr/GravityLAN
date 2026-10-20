"""API for importing subnets/VLANs from a router (Settings > Scan subnets > Import from router).

Lives under /api/network, so API tokens need network:read (saved connections) or
network:write (fetch and apply). Secrets are accepted but never returned.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.router_import import (
    ProviderKey,
    RouterImportApply,
    RouterImportApplyResult,
    RouterImportPreview,
    RouterImportRequest,
    RouterSourceResponse,
)
from app.services.router_import import RouterImportError
from app.services.router_import import service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/network/router-import", tags=["network"])


@router.get("/sources", response_model=list[RouterSourceResponse])
async def list_router_sources(db: AsyncSession = Depends(get_db)):
    """Saved router connections (address and options; which secrets are stored, never their values)."""
    return await service.list_sources(db)


@router.delete("/sources/{provider}")
async def delete_router_source(provider: ProviderKey, db: AsyncSession = Depends(get_db)):
    """Forget a saved router connection and its stored credentials."""
    if not await service.delete_source(db, provider):
        raise HTTPException(status_code=404, detail="No saved connection for this provider")
    return {"status": "ok"}


@router.post("/preview", response_model=RouterImportPreview)
async def preview_router_import(req: RouterImportRequest, db: AsyncSession = Depends(get_db)):
    """Ask the router for its networks and compare them with the scan subnets. Changes no subnet."""
    try:
        return await service.preview(db, req)
    except RouterImportError as err:
        logger.info("Router import (%s at %s) failed: %s", req.provider, req.host, err.message)
        raise HTTPException(status_code=err.status_code, detail=err.message) from None


@router.post("/apply", response_model=RouterImportApplyResult)
async def apply_router_import(req: RouterImportApply, db: AsyncSession = Depends(get_db)):
    """Add the picked networks as scan subnets; configured ones only get an empty gateway/VLAN filled in."""
    from app.api.network import _invalidate_device_views

    result = await service.apply(db, req)
    if result.added or result.updated:
        _invalidate_device_views()
    return result
