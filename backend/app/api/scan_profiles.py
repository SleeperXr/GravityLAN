"""Scan profiles management router for GravityLAN."""

import logging
from fastapi import APIRouter, Depends
from app.api.auth import get_current_admin
from app.schemas.scan import ScanProfileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scan-profiles", tags=["scanner"])

# Static list of Nmap scan profiles as approved by the user
STATIC_SCAN_PROFILES = [
    {
        "id": 1,
        "name": "Standard Discovery",
        "description": "Fast ping discovery scan of local networks",
        "nmap_arguments": "-sn -PE -PS22,80,443",
        "is_default": True
    },
    {
        "id": 2,
        "name": "Intense Scan",
        "description": "Full OS detection, services, traceroute, and fast execution",
        "nmap_arguments": "-T4 -A -v",
        "is_default": False
    },
    {
        "id": 3,
        "name": "Quick Port Scan",
        "description": "Scans the top 100 most common ports quickly",
        "nmap_arguments": "-F --open",
        "is_default": False
    }
]

@router.get("", response_model=list[ScanProfileResponse])
async def list_scan_profiles(
    current_admin: str = Depends(get_current_admin)
) -> list[ScanProfileResponse]:
    """Retrieve the list of predefined network scan profiles."""
    return [ScanProfileResponse(**p) for p in STATIC_SCAN_PROFILES]
