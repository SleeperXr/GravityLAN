from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.setting import Setting
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/login")
async def login(password: str = Body(..., embed=True), db: AsyncSession = Depends(get_db)):
    """Authenticate with a password and receive the master API token."""
    # Fetch the master token (which doubles as our 'password' for now, or we use a dedicated key)
    res_token = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
    master_setting = res_token.scalar_one_or_none()
    
    if not master_setting:
        raise HTTPException(status_code=500, detail="System not initialized. Run setup first.")
    
    # Check against a dedicated password setting if it exists, otherwise fallback to master token
    res_pass = await db.execute(select(Setting).where(Setting.key == "api.admin_password"))
    admin_pass_setting = res_pass.scalar_one_or_none()
    
    # If no password is set, the master token is the password (default)
    required_pass = admin_pass_setting.value if admin_pass_setting else master_setting.value
    

    
    if password == required_pass:
        logger.info("Login successful")
        return {"token": master_setting.value}
    
    logger.warning("Login failed: invalid password provided")
    
    raise HTTPException(status_code=401, detail="Invalid password")

class TokenCheckRequest(BaseModel):
    token: str

@router.post("/check")
async def check_auth(request: TokenCheckRequest, db: AsyncSession = Depends(get_db)):
    """Check if a token is valid via POST body to avoid URL logging."""
    token = request.token
    res_token = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
    master_setting = res_token.scalar_one_or_none()
    
    if master_setting and token == master_setting.value:
        return {"status": "ok"}
    
    raise HTTPException(status_code=401, detail="Invalid token")
