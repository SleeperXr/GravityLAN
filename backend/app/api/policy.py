"""Who may call a route: one access policy per HTTP route and WebSocket (the security matrix).

Every route declares its policy in its decorator, ``dependencies=[policy(...)]``, and nowhere else.
The policy decides the whole access question in a fixed order:

1. setup state: until the first-run wizard is completed only ``setup="open"`` routes answer
   (``setup="only"`` and public routes check this themselves);
2. authentication: browser session cookie, master token, API token (or, on a WebSocket, the
   channel's query token); ``bearer_only`` accepts the Authorization header alone;
3. caller kind: the identity must be one of ``callers`` (session, master, api_token);
4. scope: an API token needs ``scope``;
5. step-up: ``remote`` (browser session only), ``credentials`` and ``instance`` (no API tokens)
   need a recent password confirmation of a browser session.

Routes without an admin caller (``callers=PUBLIC``) are open or check their own credential
(``credential=``: agent token, install code, SSH ticket). ``tests/test_policy_matrix.py`` fails for
any route without exactly one policy, and ``scripts/security_matrix.py`` writes
``docs/security-matrix.md`` from these declarations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterator

from fastapi import Depends, HTTPException, WebSocket, WebSocketException
from fastapi.params import Depends as DependsParam
from fastapi.requests import HTTPConnection
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import stepup
from app.services.audit import record as audit, remember_actor

logger = logging.getLogger(__name__)

SESSION, MASTER, API_TOKEN = "session", "master", "api_token"
ADMIN = frozenset({SESSION, MASTER, API_TOKEN})
NO_API_TOKEN = frozenset({SESSION, MASTER})
SESSION_ONLY = frozenset({SESSION})
PUBLIC: frozenset[str] = frozenset()

SETUP_STATES = ("closed", "open", "only", "any")
# WebSocket auth types (app.api.auth.authenticate_websocket) a caller kind stands for
_WS_AUTH_TYPES = {SESSION: ("session",), MASTER: ("master", "master_legacy"), API_TOKEN: ("api_token",)}

TOKEN_FORBIDDEN_MESSAGE = (
    "Read-only token is not authorized for this administrative action. "
    "Token is not authorized for sensitive administrative actions."
)
SESSION_REQUIRED_MESSAGE = "Only a logged-in browser session can do this."
NO_POLICY_MESSAGE = "This route has no access policy."
STATE_IDENTITY = "gl_identity"
STATE_WS_AUTH = "gl_ws_auth"
_UNSET: Any = object()


@dataclass(frozen=True)
class Policy:
    """The access rule of one route; see the module docstring for the order of the checks."""

    callers: frozenset[str]
    scope: str | None = None
    step_up: str | None = None
    setup: str = "closed"
    bearer_only: bool = False
    channel: str | None = None
    agent_token: bool = False
    credential: str | None = None
    denied: str | None = None
    audit_action: str | None = None
    note: str | None = None

    @property
    def public(self) -> bool:
        return not self.callers


def _validated(p: Policy) -> Policy:
    unknown = p.callers - ADMIN
    if unknown:
        raise ValueError(f"Unknown caller kinds {sorted(unknown)}")
    if p.step_up not in (None, *stepup.CLASSES):
        raise ValueError(f"Unknown step-up class {p.step_up!r}")
    if p.setup not in SETUP_STATES:
        raise ValueError(f"Unknown setup state {p.setup!r}")
    if p.step_up == "remote" and p.callers != SESSION_ONLY:
        raise ValueError("step_up='remote' is for browser sessions only: callers=SESSION_ONLY")
    if p.step_up in stepup.CONFIRMED_CLASSES and API_TOKEN in p.callers:
        raise ValueError(f"step_up={p.step_up!r} refuses API tokens: leave api_token out of callers")
    if p.public and (p.step_up or p.scope or p.bearer_only):
        raise ValueError("A public route has no scope, step-up or bearer rule")
    if p.public and p.setup in ("closed", "open"):
        raise ValueError("A public route answers in every setup state ('any') or checks it itself ('only')")
    if not p.public and p.setup in ("only", "any"):
        raise ValueError("setup='only'/'any' is for public routes")
    if p.agent_token and p.channel is None:
        raise ValueError("agent_token is a WebSocket channel option")
    return p


def policy(
    *,
    scope: str | None = _UNSET,
    callers: frozenset[str] = ADMIN,
    step_up: str | None = None,
    setup: str | None = None,
    bearer_only: bool = False,
    channel: str | None = None,
    agent_token: bool = False,
    credential: str | None = None,
    denied: str | None = None,
    audit_action: str | None = None,
    note: str | None = None,
) -> DependsParam:
    """The access policy of one route, as a dependency for its decorator's ``dependencies=[...]``.

    ``scope`` is required whenever API tokens may call the route (``None``: any API token).
    ``channel`` marks a WebSocket and names its query-token rules (logs, scanner, agent, ssh).
    """
    callers = frozenset(callers)
    if API_TOKEN in callers and scope is _UNSET:
        raise ValueError("Routes open to API tokens name their scope (scope=None: any token)")
    if API_TOKEN not in callers and scope not in (_UNSET, None):
        raise ValueError("A scope only applies when API tokens may call the route")
    p = _validated(Policy(
        callers=callers,
        scope=None if scope is _UNSET else scope,
        step_up=step_up,
        setup=setup or ("any" if not callers else "closed"),
        bearer_only=bearer_only,
        channel=channel,
        agent_token=agent_token,
        credential=credential,
        denied=denied,
        audit_action=audit_action,
        note=note,
    ))
    dependency = _ws_dependency(p) if channel is not None else _http_dependency(p)
    dependency.policy = p  # type: ignore[attr-defined]
    return Depends(dependency)


def caller_kind(identity: str) -> str:
    if identity.startswith("session_"):
        return SESSION
    if identity.startswith("api_token:"):
        return API_TOKEN
    return MASTER


def _set_state(conn: HTTPConnection, name: str, value: Any) -> None:
    state = getattr(conn, "state", None)
    if state is not None:
        setattr(state, name, value)


async def _refuse(conn: HTTPConnection, p: Policy, kind: str) -> None:
    """403 for a caller kind the policy leaves out, recorded where the class or route asks for it."""
    if p.step_up == "remote":
        await audit(
            conn, stepup._remote_audit_action(conn.url.path), "denied",
            device_id=stepup._device_id_of(conn), detail="browser session required",
        )
        raise HTTPException(status_code=403, detail=stepup.NO_TOKEN_MESSAGE)
    if p.denied:
        if p.audit_action:
            await audit(conn, p.audit_action, "denied", detail="not a browser session")
        raise HTTPException(status_code=403, detail=p.denied)
    if kind == API_TOKEN and p.step_up in stepup.CONFIRMED_CLASSES:
        await audit(conn, f"stepup.{p.step_up}", "denied", detail="API token")
        raise HTTPException(status_code=403, detail=stepup.API_TOKEN_MESSAGE)
    raise HTTPException(status_code=403, detail=TOKEN_FORBIDDEN_MESSAGE if kind == API_TOKEN else SESSION_REQUIRED_MESSAGE)


def _http_dependency(p: Policy):
    async def enforce_policy(conn: HTTPConnection, db: AsyncSession = Depends(get_db)) -> str | None:
        if p.public:
            return None
        from app.api import auth

        if p.bearer_only and await auth._setup_completed(db):
            identity = await auth.authenticate_bearer_only(conn, db)
        else:
            identity = await auth._resolve_admin(
                conn, conn.headers.get("authorization"), conn.query_params.get("token"), db,
                setup_open=p.setup == "open",
            )
        remember_actor(conn, identity)
        _set_state(conn, STATE_IDENTITY, identity)
        if identity == "setup_mode":
            return identity

        kind = caller_kind(identity)
        if kind not in p.callers:
            await _refuse(conn, p, kind)
        if kind == API_TOKEN and p.scope:
            scopes = getattr(getattr(conn, "state", None), auth.STATE_TOKEN_SCOPES, None) or set()
            if p.scope not in scopes:
                raise auth._missing_scope_error(p.scope, conn.scope.get("method", "GET"))
        if p.step_up:
            stepup.check(conn, p.step_up)
        return identity

    return enforce_policy


class _DeferredClose:
    """The WebSocket as the authentication sees it, with ``close`` remembered instead of sent.

    The policy then refuses the handshake with ``WebSocketException`` (same code and reason), so
    the endpoint never runs for a refused caller.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self.closed: tuple[int, str | None] | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._websocket, name)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = (code, reason)


def _ws_dependency(p: Policy):
    allowed = {t for kind in p.callers for t in _WS_AUTH_TYPES[kind]}
    if p.agent_token:
        allowed.add("agent")
    if p.setup == "open":
        allowed.add("setup_bypass")

    async def enforce_ws_policy(websocket: WebSocket) -> dict | None:
        if p.public:
            return None
        from app.api import auth

        raw_id = websocket.path_params.get("device_id")
        device_id = int(raw_id) if raw_id is not None and str(raw_id).isdigit() else None
        deferred = _DeferredClose(websocket)
        info = await auth.authenticate_websocket(
            deferred, endpoint_type=p.channel, device_id=device_id, token_scope=p.scope,  # type: ignore[arg-type]
        )
        if not info.get("authenticated"):
            code, reason = deferred.closed or (4003, "Unauthorized")
            raise WebSocketException(code=code, reason=reason)
        if info.get("auth_type") not in allowed:
            raise WebSocketException(code=4003, reason="Unauthorized access level")
        remember_actor(websocket, info.get("identity") or "")
        _set_state(websocket, STATE_WS_AUTH, info)
        return info

    return enforce_ws_policy


def ws_auth(websocket: WebSocket) -> dict:
    """The authentication the WebSocket's policy accepted (auth_type, identity)."""
    return getattr(websocket.state, STATE_WS_AUTH, None) or {}


# --- reading the declarations (completeness test, matrix document) -----------------------------

@dataclass(frozen=True)
class RoutePolicy:
    method: str  # HTTP method, or "WS"
    path: str
    endpoint: str
    policies: tuple[Policy, ...]

    @property
    def policy(self) -> Policy | None:
        return self.policies[0] if len(self.policies) == 1 else None


def _policies_of(dependant) -> list[Policy]:
    found = []
    for sub in dependant.dependencies:
        p = getattr(sub.call, "policy", None)
        if isinstance(p, Policy):
            found.append(p)
        found.extend(_policies_of(sub))
    return found


def iter_route_policies(app) -> Iterator[RoutePolicy]:
    """Every HTTP method and WebSocket of ``app`` with the policies its dependencies declare."""
    from fastapi import routing
    from fastapi.routing import APIRoute, APIWebSocketRoute

    for ctx in routing.iter_route_contexts(app.routes):
        original = ctx.original_route
        if not isinstance(original, (APIRoute, APIWebSocketRoute)):
            continue
        found = tuple(_policies_of(ctx.dependant))
        name = f"{ctx.endpoint.__module__}.{ctx.endpoint.__name__}"
        methods = sorted(ctx.methods) if isinstance(original, APIRoute) else ["WS"]
        for method in methods:
            yield RoutePolicy(method, ctx.path, name, found)
