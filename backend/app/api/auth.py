import hmac
from fastapi import APIRouter, Depends, HTTPException, Body, Response, Request, Header, WebSocket, Query
from fastapi.requests import HTTPConnection
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.setting import Setting
from app.config import settings
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

def _secure_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())

async def get_current_admin(
    conn: HTTPConnection,
    authorization: str | None = Header(None),
    token: str | None = Query(None),
    db: AsyncSession = Depends(get_db)
) -> str:
    """
    Dependency to validate authentication via Cookie, Authorization header, or Query param.
    Works for both HTTP Requests and WebSockets.
    """
    token_val = None
    
    # 1. Try Header (only for HTTP)
    if authorization and authorization.startswith("Bearer "):
        token_val = authorization.removeprefix("Bearer ").strip()
    
    # 2. Try Cookie (works for both)
    if not token:
        token = conn.cookies.get("gravitylan_token")
        
    # 0. Check if setup is complete (Bypass if not)
    from app.models.setting import Setting
    setup_res = await db.execute(select(Setting).where(Setting.key == "setup.complete"))
    setup_setting = setup_res.scalar_one_or_none()
    is_setup_done = setup_setting is not None and setup_setting.value == "true"
    
    if not is_setup_done:
        return "setup_mode"

    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
        
    res_token = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
    master_setting = res_token.scalar_one_or_none()
    
    if master_setting and _secure_compare(token, master_setting.value):
        return token
        
    raise HTTPException(status_code=401, detail="Invalid or expired token")

@router.post("/login")
async def login(
    response: Response,
    password: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    """Authenticate and set a secure httpOnly cookie."""
    res_token = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
    master_setting = res_token.scalar_one_or_none()
    
    if not master_setting:
        raise HTTPException(status_code=500, detail="System not initialized. Run setup first.")
    
    res_pass = await db.execute(select(Setting).where(Setting.key == "api.admin_password"))
    admin_pass_setting = res_pass.scalar_one_or_none()
    
    required_pass = admin_pass_setting.value if admin_pass_setting else master_setting.value
    
    if _secure_compare(password, required_pass):
        logger.info("Login successful, setting httpOnly cookie")
        
        # Set httpOnly cookie
        response.set_cookie(
            key="gravitylan_token",
            value=master_setting.value,
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookies, # Set to True if using HTTPS in prod
            path="/",
            max_age=60 * 60 * 24 * 7 # 7 days
        )
        return {
            "status": "ok", 
            "message": "Login successful",
            "token": master_setting.value
        }
    
    logger.warning("Login failed: invalid password provided")
    raise HTTPException(status_code=401, detail="Invalid password")

@router.post("/logout")
async def logout(response: Response):
    """Clear the authentication cookie."""
    response.delete_cookie(key="gravitylan_token", path="/")
    return {"status": "ok", "message": "Logged out"}

@router.post("/check")
async def check_auth(token: str = Depends(get_current_admin)):
    """Check if currently authenticated (via dependency)."""
    return {"status": "ok"}
