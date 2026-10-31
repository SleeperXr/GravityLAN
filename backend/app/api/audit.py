"""Read the audit log (newest first, filtered, paged by id)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.audit import AuditEvent
from app.services.audit import RETENTION_DAYS

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor: str
    source_ip: str
    action: str
    result: str
    device_id: int | None
    target: str
    detail: str

    @field_validator("created_at")
    @classmethod
    def _as_utc(cls, value: datetime) -> datetime:
        """Stored naive in UTC; sent with its zone so browsers do not read it as local time."""
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class AuditPage(BaseModel):
    items: list[AuditEventOut]
    has_more: bool
    retention_days: int


@router.get("", response_model=AuditPage)
async def list_audit_events(
    action: str | None = Query(
        None, max_length=200, description="Actions or their prefixes, comma-separated, e.g. 'agent,ssh.terminal'",
    ),
    result: str | None = Query(None, pattern="^(ok|failed|denied)$"),
    device_id: int | None = None,
    q: str | None = Query(None, max_length=100, description="Search in target, actor and source IP"),
    before_id: int | None = Query(None, description="Paging: entries older than this id"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> AuditPage:
    query = select(AuditEvent)
    prefixes = [p.strip() for p in (action or "").split(",") if p.strip()]
    if prefixes:
        query = query.where(or_(*(
            or_(AuditEvent.action == p, AuditEvent.action.startswith(f"{p}.")) for p in prefixes
        )))
    if result:
        query = query.where(AuditEvent.result == result)
    if device_id is not None:
        query = query.where(AuditEvent.device_id == device_id)
    if q:
        like = f"%{q}%"
        query = query.where(or_(AuditEvent.target.ilike(like), AuditEvent.actor.ilike(like), AuditEvent.source_ip.ilike(like)))
    if before_id is not None:
        query = query.where(AuditEvent.id < before_id)
    rows = (await db.execute(query.order_by(AuditEvent.id.desc()).limit(limit + 1))).scalars().all()
    return AuditPage(items=rows[:limit], has_more=len(rows) > limit, retention_days=RETENTION_DAYS)
