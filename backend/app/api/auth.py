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

from app.services.auth_service import hash_password, verify_password, looks_hashed, secure_compare
from app.services.session_service import session_store

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
    # 0. Check if setup is complete (Bypass if not)
    from app.models.setting import Setting
    setup_res = await db.execute(select(Setting).where(Setting.key == "setup.complete"))
    setup_setting = setup_res.scalar_one_or_none()
    is_setup_done = setup_setting is not None and setup_setting.value == "true"
    
    if not is_setup_done:
        return "setup_mode"

    # 1. Try Browser Cookie (Primary channel for Browser sessions)
    cookie_token = conn.cookies.get("gravitylan_token")
    if cookie_token:
        if cookie_token.startswith("session_"):
            session = session_store.get_session(cookie_token)
            if session:
                # Weak plausibility check for User-Agent (not a hard security guarantee)
                req_ua = conn.headers.get("user-agent")
                if session.user_agent and req_ua and session.user_agent != req_ua:
                    logger.warning("Session User-Agent mismatch: expected '%s', got '%s'", session.user_agent, req_ua)
                return cookie_token
            raise HTTPException(status_code=401, detail="Session expired or invalid")
        else:
            # Deprecated Legacy Cookie Fallback (Master-Token in Cookie)
            res_token = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
            master_setting = res_token.scalar_one_or_none()
            if master_setting and secure_compare(cookie_token, master_setting.value):
                logger.warning(
                    "DEPRECATION WARNING: Master-Token used in browser cookie. "
                    "This legacy authentication path is deprecated and will be removed in a future release."
                )
                return cookie_token
            raise HTTPException(status_code=401, detail="Invalid token")

    # 2. Try Authorization Header (Primary channel for external API/Agent calls)
    if authorization and authorization.startswith("Bearer "):
        token_val = authorization.removeprefix("Bearer ").strip()
        # Strictly reject Session IDs in the Authorization Header
        if token_val.startswith("session_"):
            logger.warning("Security Warning: Session ID submitted in Authorization Header. Rejected.")
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication method. Session IDs are only accepted via cookies."
            )
        
        res_token = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
        master_setting = res_token.scalar_one_or_none()
        if master_setting and secure_compare(token_val, master_setting.value):
            return token_val
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # 3. Special Fallback Channel: Query Parameter (WebSockets ONLY)
    if token:
        is_websocket = conn.scope.get("type") == "websocket"
        if not is_websocket:
            logger.warning("Security Warning: Attempted query parameter authentication on non-WebSocket route. Blocked.")
            raise HTTPException(
                status_code=401,
                detail="Query parameter authentication is restricted to WebSockets."
            )
        
        if token.startswith("session_"):
            session = session_store.get_session(token)
            if session:
                return token
        else:
            res_token = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
            master_setting = res_token.scalar_one_or_none()
            if master_setting and secure_compare(token, master_setting.value):
                return token
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    raise HTTPException(status_code=401, detail="Missing authentication token")

async def authenticate_websocket(
    websocket: WebSocket,
    endpoint_type: str,  # "logs" (Logs), "scanner" (Scan Status), "agent" (Agent metrics)
    device_id: int | None = None,
    db: AsyncSession | None = None
) -> dict:
    """
    Centralized, secure helper to authenticate WebSocket connections.
    Enforces strict endpoint classification and channel policies.
    
    Supports:
    1. Browser-based clients: Authenticates via 'gravitylan_token' cookie (Session ID).
    2. External scripts / CLI: Authenticates via 'token' query parameter (Master Token, ONLY on 'logs' endpoints).
    3. Specialized Agents: Authenticates via 'token' query parameter (Agent Token, ONLY on 'agent' endpoints).
    4. Setup Bypass: Allowed ONLY on 'scanner' endpoints during initial configuration.
    
    Returns:
        dict: A dictionary containing auth info:
            {
                "authenticated": bool,
                "auth_type": "session" | "master" | "agent" | "master_legacy" | "setup_bypass",
                "identity": str
            }
    """
    if db is None:
        from app.database import async_session
        async with async_session() as session_ctx:
            return await _authenticate_websocket_impl(websocket, endpoint_type, device_id, session_ctx)
    else:
        return await _authenticate_websocket_impl(websocket, endpoint_type, device_id, db)

async def _authenticate_websocket_impl(
    websocket: WebSocket,
    endpoint_type: str,
    device_id: int | None,
    db: AsyncSession
) -> dict:
    from app.models.setting import Setting
    from app.models.agent import AgentToken
    from app.services.auth_service import secure_compare
    from sqlalchemy import select

    # 1. Setup Bypass Check
    # Only "scanner" endpoint allows setup bypass so the wizard can show progress of initial scans.
    setup_res = await db.execute(select(Setting).where(Setting.key == "setup.complete"))
    setup_setting = setup_res.scalar_one_or_none()
    is_setup_done = setup_setting is not None and setup_setting.value == "true"

    if not is_setup_done:
        if endpoint_type == "scanner":
            return {
                "authenticated": True,
                "auth_type": "setup_bypass",
                "identity": "anonymous"
            }
        else:
            logger.warning(
                "WebSocket connection rejected: Setup bypass requested on non-scanner route '%s'.",
                endpoint_type
            )
            await websocket.close(code=4003, reason="Setup incomplete")
            return {"authenticated": False}

    cookie_token = websocket.cookies.get("gravitylan_token")
    query_token = websocket.query_params.get("token")

    # Reject any attempts to pass a Session ID (?token=session_...) via query params globally
    if query_token and query_token.startswith("session_"):
        logger.warning("WebSocket connection rejected: Session-IDs via query parameters are strictly forbidden.")
        await websocket.close(code=4003, reason="Query-based session auth forbidden")
        return {"authenticated": False}

    # 2. Browser Session Validation (via HTTP Cookie)
    # Both "logs", "scanner", and "agent" endpoints support Cookie auth (UI clients subscribing)
    if cookie_token and cookie_token.startswith("session_"):
        session = session_store.get_session(cookie_token)
        if session:
            # User-Agent check (weak mitigation signal)
            req_ua = websocket.headers.get("user-agent")
            if session.user_agent and req_ua and session.user_agent != req_ua:
                logger.warning(
                    "WebSocket Session User-Agent mismatch: expected '%s', got '%s'",
                    session.user_agent, req_ua
                )
            return {
                "authenticated": True,
                "auth_type": "session",
                "identity": cookie_token
            }
        # Reject and close if session cookie is invalid
        logger.warning("WebSocket connection rejected: Expired or invalid session cookie.")
        await websocket.close(code=4003, reason="Session expired or invalid")
        return {"authenticated": False}

    # 3. Dedicated Query Parameter Auth per channel policy
    if query_token:
        # A. Logs ("logs") allows ONLY Master-Token in query params for external Admin CLIs/Tools
        if endpoint_type == "logs":
            master_res = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
            master_setting = master_res.scalar_one_or_none()
            master_token = master_setting.value if master_setting else None

            if master_token and secure_compare(query_token, master_token):
                return {
                    "authenticated": True,
                    "auth_type": "master",
                    "identity": query_token
                }
            logger.warning("WebSocket connection rejected: Invalid master token in query params for logs route.")
            await websocket.close(code=4003, reason="Unauthorized")
            return {"authenticated": False}

        # B. Agent ("agent") allows ONLY Agent-Token in query params for physical/remote agents
        elif endpoint_type == "agent":
            if device_id is not None:
                agent_res = await db.execute(
                    select(AgentToken).where(
                        AgentToken.device_id == device_id,
                        AgentToken.is_active.is_(True)
                    )
                )
                agent_token_obj = agent_res.scalar_one_or_none()
                if agent_token_obj and secure_compare(query_token, agent_token_obj.token):
                    return {
                        "authenticated": True,
                        "auth_type": "agent",
                        "identity": query_token
                    }
            logger.warning("WebSocket connection rejected: Invalid agent token or device mismatch in query params.")
            await websocket.close(code=4003, reason="Unauthorized")
            return {"authenticated": False}

        # C. Scanner ("scanner") does not accept any query params (UI only)
        else:
            logger.warning("WebSocket connection rejected: Query parameters are forbidden on scanner route.")
            await websocket.close(code=4003, reason="Query parameters forbidden")
            return {"authenticated": False}

    # 4. Deprecated Legacy Cookie Fallback (Master-Token in Cookie)
    if cookie_token:
        master_res = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
        master_setting = master_res.scalar_one_or_none()
        master_token = master_setting.value if master_setting else None
        if master_token and secure_compare(cookie_token, master_token):
            logger.warning(
                "DEPRECATION WARNING: Master-Token used in browser cookie for WebSocket auth. "
                "This legacy path is deprecated and will be removed in a future release."
            )
            return {
                "authenticated": True,
                "auth_type": "master_legacy",
                "identity": cookie_token
            }

    # 5. Missing Credentials
    logger.warning("WebSocket connection rejected: Missing authentication token.")
    await websocket.close(code=4001, reason="Missing authentication token")
    return {"authenticated": False}

@router.post("/login")
async def login(
    request: Request,
    response: Response,
    password: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db)
):
    """Authenticate and set a secure httpOnly session cookie."""
    res_token = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
    master_setting = res_token.scalar_one_or_none()
    
    if not master_setting:
        raise HTTPException(status_code=500, detail="System not initialized. Run setup first.")
    
    res_pass = await db.execute(select(Setting).where(Setting.key == "api.admin_password"))
    admin_pass_setting = res_pass.scalar_one_or_none()
    
    required_pass = admin_pass_setting.value if admin_pass_setting else master_setting.value
    
    is_valid = False
    needs_migration = False

    if looks_hashed(required_pass):
        is_valid = verify_password(password, required_pass)
    else:
        # Legacy plaintext comparison
        is_valid = secure_compare(password, required_pass)
        if is_valid:
            needs_migration = True
    
    if is_valid:
        logger.info("Login successful, generating lock-free in-memory session")
        
        # Auto-migrate to hashed password if it was plaintext
        if needs_migration:
            logger.info("Migrating legacy plaintext password to hash")
            hashed = hash_password(password)
            if admin_pass_setting:
                admin_pass_setting.value = hashed
            else:
                db.add(Setting(key="api.admin_password", value=hashed, category="system"))
            await db.commit()

        # Create session in store
        user_agent = request.headers.get("user-agent")
        session_id = session_store.create_session(user_agent=user_agent)

        # Set httpOnly session cookie
        response.set_cookie(
            key="gravitylan_token",
            value=session_id,
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookies,
            path="/",
            max_age=60 * 60 * 24 * 7 # 7 days
        )
        return {
            "status": "ok", 
            "message": "Login successful"
        }
    
    logger.warning("Login failed: invalid password provided")
    raise HTTPException(status_code=401, detail="Invalid password")

@router.post("/logout")
async def logout(request: Request, response: Response):
    """Clear the authentication cookie and invalidate the in-memory session."""
    cookie_token = request.cookies.get("gravitylan_token")
    if cookie_token and cookie_token.startswith("session_"):
        session_store.delete_session(cookie_token)
    response.delete_cookie(key="gravitylan_token", path="/")
    return {"status": "ok", "message": "Logged out"}

@router.post("/check")
async def check_auth(token: str = Depends(get_current_admin)):
    """Check if currently authenticated (via dependency)."""
    return {"status": "ok"}
