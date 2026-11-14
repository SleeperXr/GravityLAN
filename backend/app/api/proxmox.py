"""Admin settings for the read-only Proxmox VE integration (Settings > Proxmox VE)."""
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_admin
from app.database import get_db
from app.models.proxmox import ProxmoxIntegration
from app.services.audit import record as audit
from app.services.cache_service import discovery_cache
from app.services.proxmox import ProxmoxError, sync_lock, sync_proxmox, write_lock
from app.services.secret_vault import VaultError, vault
from app.services.stepup import require_step_up

router = APIRouter(prefix="/api/settings/proxmox", tags=["proxmox"], dependencies=[Depends(get_current_admin)])

TOKEN_ID_PATTERN = re.compile(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+")


class ProxmoxSettings(BaseModel):
    enabled: bool = False
    url: str = Field(default="", max_length=500)
    token_id: str = Field(default="", max_length=255)
    token_secret: SecretStr | None = None
    verify_tls: bool = True

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return ""
        try:
            parsed = urlsplit(value)
            valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                     and not parsed.password and not parsed.query and not parsed.fragment
                     and parsed.path in ("", "/api2/json") and not any(c.isspace() for c in value))
            _ = parsed.port  # raises ValueError for a port out of range
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Use an HTTPS Proxmox address such as https://pve.example:8006, without credentials or a query.")
        return f"https://{parsed.netloc}"

    @field_validator("token_id")
    @classmethod
    def validate_token_id(cls, value: str) -> str:
        value = value.strip()
        if value and not TOKEN_ID_PATTERN.fullmatch(value):
            raise ValueError("Token ID must have the form user@realm!token-name.")
        return value


def public_settings(connection: ProxmoxIntegration | None) -> dict:
    """The settings without the secret; has_token_secret says whether one is stored."""
    if not connection:
        return {"enabled": False, "url": "", "token_id": "", "verify_tls": True,
                "has_token_secret": False, "last_sync": None, "last_error": None}
    return {"enabled": connection.enabled, "url": connection.url, "token_id": connection.token_id,
            "verify_tls": connection.verify_tls, "has_token_secret": bool(connection.encrypted_secret),
            "last_sync": connection.last_sync, "last_error": connection.last_error}


@router.get("")
async def get_settings(db: AsyncSession = Depends(get_db)):
    return public_settings(await db.get(ProxmoxIntegration, 1))


@router.put("", dependencies=[Depends(require_step_up("credentials"))])
async def save_settings(body: ProxmoxSettings, request: Request, db: AsyncSession = Depends(get_db)):
    async with write_lock:
        connection = await db.get(ProxmoxIntegration, 1)
        secret = body.token_secret.get_secret_value() if body.token_secret else ""
        if secret and (len(secret) > 4096 or any(not 33 <= ord(c) <= 126 for c in secret)):
            raise HTTPException(400, "Invalid API token secret.")
        stored = bool(connection and connection.encrypted_secret)
        if body.enabled and (not body.url or not body.token_id or not (secret or stored)):
            raise HTTPException(400, "An enabled connection needs an API address, token ID and token secret.")
        # A stored token must never be sent to a server or token ID it was not entered for
        if stored and not secret and (body.url != connection.url or body.token_id != connection.token_id):
            raise HTTPException(400, "Enter the token secret again when changing the server or token ID.")
        if not connection:
            connection = ProxmoxIntegration(id=1)
            db.add(connection)
        if secret:
            try:
                connection.encrypted_secret = vault.encrypt(secret)
            except VaultError:
                raise HTTPException(500, "Cannot encrypt the Proxmox token. Check the secret vault key.")
        connection.enabled = body.enabled
        connection.url = body.url
        connection.token_id = body.token_id
        connection.verify_tls = body.verify_tls
        connection.last_error = None
        await db.commit()
        discovery_cache.invalidate()
        result = public_settings(connection)
    await audit(request, "proxmox.save", target=urlsplit(body.url).hostname or "",
                detail=f"enabled={body.enabled} verify_tls={body.verify_tls} new_secret={bool(secret)}")
    return result


@router.delete("", status_code=204, dependencies=[Depends(require_step_up("credentials"))])
async def disconnect(request: Request, db: AsyncSession = Depends(get_db)):
    async with write_lock:
        connection = await db.get(ProxmoxIntegration, 1)
        if not connection:
            return
        host = urlsplit(connection.url).hostname or ""
        await db.delete(connection)
        await db.commit()
        discovery_cache.invalidate()
    await audit(request, "proxmox.delete", target=host)


@router.post("/sync")
async def synchronize(db: AsyncSession = Depends(get_db)):
    if sync_lock.locked():
        raise HTTPException(409, "A Proxmox sync is already running. Try again shortly.")
    try:
        return await sync_proxmox(db)
    except ProxmoxError as exc:
        raise HTTPException(502, str(exc))
