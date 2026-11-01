"""Step-up: a browser session confirms the admin password again before sensitive actions (AP-12, AP-13).

A confirmation grants one class of actions to one session for ``security.stepup_minutes`` (default 10,
1 to 60). Grants live in memory next to the sessions themselves and end with them. Endpoints declare
their class with ``Depends(require_step_up("remote"))``; without a grant they answer 403 with the
header ``X-Step-Up: <class>``, which GravityUI answers with its password dialog and a retry.

Remote actions (terminal, agent install/removal, install codes, package updates) require a browser
session with confirmation: master and API tokens are refused with 403 and recorded in the audit log
(AP-13).
"""

import time

from fastapi import HTTPException, Request
from sqlalchemy import select
from starlette.requests import HTTPConnection

from app.services.audit import record as audit
from app.services.session_service import session_store

# remote: terminals, agent install/removal, install codes, package updates; credentials: SSH keys and
# connections, known hosts, API tokens, webhooks; instance: backup export/import, database reset, this setting
CLASSES = ("remote", "credentials", "instance")
SETTING_KEY = "security.stepup_minutes"
DEFAULT_MINUTES = 10
MIN_MINUTES, MAX_MINUTES = 1, 60
HEADER = "X-Step-Up"
MESSAGE = "Confirm your password first. In the classic view this action is only available in GravityUI."
NO_TOKEN_MESSAGE = (
    "Remote access requires a logged-in browser session with password confirmation; "
    "API and master tokens are not allowed."
)


class StepUpStore:
    def __init__(self) -> None:
        self._grants: dict[tuple[str, str], float] = {}

    def grant(self, session_id: str, cls: str, seconds: float) -> float:
        """Allow ``cls`` for ``session_id`` for ``seconds``; returns the expiry (monotonic)."""
        self._prune()
        expires = time.monotonic() + seconds
        self._grants[(session_id, cls)] = expires
        return expires

    def is_granted(self, session_id: str, cls: str) -> bool:
        return self._grants.get((session_id, cls), 0.0) > time.monotonic()

    def remaining(self, session_id: str) -> dict[str, int]:
        """Seconds left per class for one session (expired classes left out)."""
        now = time.monotonic()
        return {cls: int(exp - now) for (sid, cls), exp in self._grants.items() if sid == session_id and exp > now}

    def clear(self) -> None:
        self._grants.clear()

    def _prune(self) -> None:
        now = time.monotonic()
        for key in [k for k, exp in self._grants.items() if exp <= now]:
            del self._grants[key]


store = StepUpStore()


def clamp_minutes(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MINUTES
    return min(max(minutes, MIN_MINUTES), MAX_MINUTES)


async def grant_minutes(db) -> int:
    from app.models.setting import Setting
    row = (await db.execute(select(Setting).where(Setting.key == SETTING_KEY))).scalar_one_or_none()
    return clamp_minutes(row.value) if row and row.value else DEFAULT_MINUTES


def session_of(conn: HTTPConnection) -> str | None:
    """The live browser session of a request, or None (API/master token, no or expired cookie)."""
    cookie = conn.cookies.get("gravitylan_token") or ""
    return cookie if cookie.startswith("session_") and session_store.get_session(cookie) else None


def _remote_audit_action(path: str) -> str:
    if "/ssh/" in path:
        return "ssh.terminal.open"
    if "/enroll/" in path:
        return "agent.install_code"
    if "/deploy/" in path:
        return "agent.deploy"
    if "/uninstall/" in path:
        return "agent.uninstall"
    return "agent.patches"


def _device_id_of(conn: HTTPConnection) -> int | None:
    raw = conn.path_params.get("device_id")
    return int(raw) if raw is not None and str(raw).isdigit() else None


def check(conn: HTTPConnection, cls: str) -> None:
    """Raise 403 + X-Step-Up when a browser session has no grant for ``cls``."""
    session_id = session_of(conn)
    if session_id is not None and not store.is_granted(session_id, cls):
        raise HTTPException(status_code=403, detail=MESSAGE, headers={HEADER: cls})


def require_step_up(cls: str):
    """FastAPI dependency for an endpoint of class ``cls``."""
    if cls not in CLASSES:
        raise ValueError(f"Unknown step-up class {cls!r}")

    async def dependency(request: Request) -> None:
        if cls == "remote" and session_of(request) is None:
            await audit(
                request,
                _remote_audit_action(request.url.path),
                "denied",
                device_id=_device_id_of(request),
                detail="browser session required",
            )
            raise HTTPException(status_code=403, detail=NO_TOKEN_MESSAGE)
        check(request, cls)

    return dependency
