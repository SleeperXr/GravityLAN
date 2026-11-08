"""Agent Patches API — Package update query, preparation, and WebSocket execution stream."""

import inspect
import logging
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_admin
from app.config import settings
from app.database import async_session, get_db
from app.models.agent import DeviceMetrics
from app.models.device import Device
from app.models.ssh import SshKnownHost
from app.schemas.agent import (
    AgentDeployRequest,
    DevicePatchesResponse,
    PackageUpdateInfo,
    PatchActionRequest,
    runner_password,
)
from app.services.agent_telemetry import _latest_metrics, _ws_subscribers
from app.services.audit import actor_from_identity
from app.services.audit import record as audit
from app.services.patch_service import list_device_updates, run_ssh_command_stream
from app.services.session_service import has_browser_session
from app.services.ssh_credentials import (
    StoredLoginError,
    resolve_key_profile,
    resolve_stored_key,
)
from app.services.ssh_utils import PinnedHostKey, TofuHostKeyPolicy
from app.services.stepup import require_step_up

logger = logging.getLogger(__name__)

patch_router = APIRouter()

# Cache for temporary patch session credentials
_temp_patch_tokens: dict[str, dict[str, Any]] = {}
PATCH_TOKEN_TTL_SECONDS = 60


@dataclass(slots=True)
class PatchStreamParams:
    """Parameters for streaming package update execution over WebSocket."""

    websocket: WebSocket
    device_id: int
    mode: str
    actor: str
    ssh: dict[str, Any]
    optional: dict[str, Any]
    cmd: str


def _get_agent_attr(name: str, default: Any) -> Any:
    """Resolve attribute from app.api.agent if monkeypatched by test doubles."""
    mod = sys.modules.get("app.api.agent")
    if mod and hasattr(mod, name):
        return getattr(mod, name)
    return default


async def _persist_captured_host_key(
    db: AsyncSession,
    host: str,
    port: int,
    captured: Any,
) -> None:
    """Persist a newly learned SSH host key (TOFU) if no entry exists yet."""
    existing = (
        await db.execute(
            select(SshKnownHost).where(SshKnownHost.host == host, SshKnownHost.port == port)
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            SshKnownHost(
                host=host,
                port=port,
                key_type=captured.key_type,
                fingerprint=captured.fingerprint,
                public_key=captured.public_key,
            )
        )
        await db.commit()


async def _resolve_patch_credentials(
    db: AsyncSession,
    device: Device,
    request: AgentDeployRequest | PatchActionRequest,
    http_request: Request,
) -> tuple[str, int, str, str | None, str | None, str | None, PinnedHostKey | None]:
    """Resolve (host_ip, ssh_port, ssh_user, ssh_password, ssh_key, ssh_key_passphrase, pinned_host_key)."""
    runner_pwd = runner_password(request)

    if request.profile_id is not None:
        if not has_browser_session(http_request):
            raise HTTPException(
                status_code=403,
                detail="Saved SSH connections can only be used from a logged-in browser session.",
            )
        try:
            login = await resolve_key_profile(db, request.profile_id, device)
        except StoredLoginError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        await db.commit()
        return login.host, login.port, login.username, runner_pwd, login.private_key, login.passphrase, login.pinned

    host_ip = device.ip
    ssh_port = request.ssh_port
    ssh_user = request.ssh_user
    ssh_password = runner_pwd
    ssh_key = request.ssh_key
    ssh_passphrase = request.key_passphrase

    if request.key_id is not None:
        if not has_browser_session(http_request):
            raise HTTPException(
                status_code=403,
                detail="Saved SSH keys can only be used from a logged-in browser session.",
            )
        try:
            ssh_key, ssh_passphrase = await resolve_stored_key(
                db, request.key_id, request.key_passphrase
            )
        except StoredLoginError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        await db.commit()

    stmt = select(SshKnownHost).where(SshKnownHost.host == host_ip, SshKnownHost.port == ssh_port)
    known = (await db.execute(stmt)).scalar_one_or_none()
    pinned = PinnedHostKey(key_type=known.key_type, fingerprint=known.fingerprint) if known else None

    return host_ip, ssh_port, ssh_user, ssh_password, ssh_key, ssh_passphrase, pinned


def _ssh_kwargs_for(fn: Any, base: dict[str, Any], **optional: Any) -> dict[str, Any]:
    """``base`` plus the optional SSH arguments ``fn`` accepts; values that are None are left out.

    Test doubles of the probe and stream functions may take fewer arguments than the real ones.
    """
    params = inspect.signature(fn).parameters
    accepts_any = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    kwargs = dict(base)
    for name, value in optional.items():
        if value is not None and (accepts_any or name in params):
            kwargs[name] = value
    return kwargs


def _format_package_updates(packages_data: list[dict[str, Any]]) -> list[PackageUpdateInfo]:
    """Convert raw package dictionaries to structured PackageUpdateInfo objects."""
    return [
        PackageUpdateInfo(
            package=p["package"],
            current_version=p["current_version"],
            new_version=p["new_version"],
            repo=p.get("repo"),
        )
        for p in packages_data
    ]


@patch_router.post("/patches/{device_id}/query", response_model=DevicePatchesResponse, dependencies=[Depends(get_current_admin), Depends(require_step_up("remote"))])
async def query_device_patches(
    device_id: int,
    request: AgentDeployRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: str = Depends(get_current_admin),
) -> DevicePatchesResponse:
    """Query available package updates from the remote host using SSH credentials."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    host_ip, ssh_port, ssh_user, ssh_password, ssh_key, ssh_passphrase, pinned = (
        await _resolve_patch_credentials(db, device, request, http_request)
    )
    tofu = TofuHostKeyPolicy() if pinned is None and not settings.ssh_strict_mode else None

    query_kwargs = {
        "host_ip": host_ip,
        "ssh_user": ssh_user,
        "ssh_password": ssh_password,
        "ssh_key": ssh_key,
        "ssh_port": ssh_port,
        "ssh_key_passphrase": ssh_passphrase,
    }
    list_updates_fn = _get_agent_attr("list_device_updates", list_device_updates)
    call_kwargs = _ssh_kwargs_for(
        list_updates_fn,
        query_kwargs,
        pinned_host_key=pinned,
        tofu_policy=tofu,
    )

    result = await list_updates_fn(**call_kwargs)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    if tofu and tofu.captured:
        await _persist_captured_host_key(db, host_ip, ssh_port, tofu.captured)

    return DevicePatchesResponse(
        device_id=device_id,
        patch_manager=result["patch_manager"],
        packages=_format_package_updates(result["packages"]),
        major_upgrade_available=result.get("major_upgrade_available"),
    )


@patch_router.post("/patches/{device_id}/prepare", dependencies=[Depends(get_current_admin), Depends(require_step_up("remote"))])
async def prepare_patch_action(
    device_id: int,
    request: PatchActionRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: str = Depends(get_current_admin),
):
    """Generate a temporary token to run updates over WebSocket."""
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    host_ip, ssh_port, ssh_user, ssh_password, ssh_key, ssh_passphrase, pinned = (
        await _resolve_patch_credentials(db, device, request, http_request)
    )

    # Generate a unique token
    token = f"patch_tok_{uuid.uuid4().hex}"

    # Store credentials and parameters temporarily (expires in 60s)
    _temp_patch_tokens[token] = {
        "device_id": device_id,
        "host_ip": host_ip,
        "ssh_user": ssh_user,
        "ssh_password": ssh_password,
        "ssh_key": ssh_key,
        "ssh_key_passphrase": ssh_passphrase,
        "ssh_port": ssh_port,
        "pinned_host_key": pinned,
        "mode": request.mode,
        "created_at": time.time(),
    }

    # Clean up expired tokens
    now = time.time()
    expired = [k for k, v in _temp_patch_tokens.items() if now - v["created_at"] > PATCH_TOKEN_TTL_SECONDS]
    for k in expired:
        _temp_patch_tokens.pop(k, None)

    return {"patch_token": token}


async def _send_ws_text(websocket: WebSocket, text: str) -> bool:
    """Send text to the client; False when it has already disconnected."""
    try:
        await websocket.send_text(text)
        return True
    except (WebSocketDisconnect, RuntimeError, OSError):
        return False


async def _consume_patch_session(websocket: WebSocket, device_id: int) -> dict | None:
    """Validate and consume the one-shot patch session token; returns session data or None.

    The error message is awaited (not a fire-and-forget task), so it reaches the
    client before the caller closes the WebSocket.
    """
    patch_token = websocket.query_params.get("patch_token")
    session_data = _temp_patch_tokens.pop(patch_token, None) if patch_token else None
    if session_data is None or time.time() - session_data["created_at"] > PATCH_TOKEN_TTL_SECONDS:
        await _send_ws_text(websocket, "\r\n[Error] Invalid or expired patch session token. Please try again.\r\n")
        return None

    if session_data["device_id"] != device_id:
        await _send_ws_text(websocket, "\r\n[Error] Session token device ID mismatch.\r\n")
        return None
    return session_data


def _build_update_command(pkg_manager: str, mode: str) -> str | None:
    """Build the shell command for the given package manager and update mode."""
    if pkg_manager == "apt":
        if mode == "security-only":
            return 'DEBIAN_FRONTEND=noninteractive apt-get install --only-upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" $(apt-get -s upgrade | awk \'/^Inst/ { if ($0 ~ /security/ || $0 ~ /Security/) print $2 }\')'
        return 'DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"'
    if pkg_manager == "dnf":
        return "dnf upgrade --security -y" if mode == "security-only" else "dnf upgrade -y"
    if pkg_manager == "yum":
        return "yum update --security -y" if mode == "security-only" else "yum update -y"
    return None


async def _push_metrics_to_subscribers(device_id: int) -> None:
    """Push the current snapshot to all WebSocket subscribers (best-effort)."""
    if device_id not in _ws_subscribers or device_id not in _latest_metrics:
        return
    # A snapshot: dashboards connect and disconnect (or get closed on revocation) while we await
    for ws in list(_ws_subscribers.get(device_id, ())):
        try:
            await ws.send_json({"type": "metrics", "data": _latest_metrics[device_id]})
        except (WebSocketDisconnect, RuntimeError, OSError) as exc:
            logger.debug("Failed to push patch metrics to subscriber for device %s: %s", device_id, exc)


async def _clear_device_patch_state(device_id: int) -> None:
    """Reset patch counters in DB and push updated metrics to subscribers."""
    try:
        async with async_session() as db:
            metrics_res = await db.execute(
                select(DeviceMetrics)
                .where(DeviceMetrics.device_id == device_id)
                .order_by(DeviceMetrics.timestamp.desc())
            )
            last_metric = metrics_res.scalars().first()
            if not last_metric:
                return
            last_metric.patch_available = 0
            last_metric.patch_security = 0
            await db.commit()
    except SQLAlchemyError as exc:
        logger.error("Failed to update database metrics after patch execution for device %s: %s", device_id, exc)
        return

    if device_id in _latest_metrics:
        _latest_metrics[device_id]["patch_available"] = 0
        _latest_metrics[device_id]["patch_security"] = 0
        await _push_metrics_to_subscribers(device_id)


async def _probe_package_manager(
    websocket: WebSocket, device_id: int, mode: str, actor: Any, ssh: dict[str, Any], optional: dict[str, Any],
) -> str | None:
    """Ask the host which package manager it has; None after the client was told why the run stops."""
    host_ip = ssh["host_ip"]
    list_updates_fn = _get_agent_attr("list_device_updates", list_device_updates)
    try:
        probe = await list_updates_fn(**_ssh_kwargs_for(list_updates_fn, ssh, **optional))
    except Exception as e:
        logger.exception("SSH probe failed for device %s", device_id)
        await audit(websocket, "agent.patches", "failed", device_id=device_id, target=host_ip, detail=f"{mode}: SSH probe failed", actor=actor)
        await websocket.send_text(f"[Error] SSH probe failed: {e}\r\n")
        await websocket.close()
        return None

    pkg_manager = probe.get("patch_manager")
    probe_error = probe.get("error")
    # A refused password fails the run too; any other probe error (one broken repository makes
    # apt-get update fail) must not block the upgrade, which reports its own errors
    if probe_error and (probe.get("sudo_rejected") or not pkg_manager):
        await audit(websocket, "agent.patches", "failed", device_id=device_id, target=host_ip, detail=f"{mode}: {probe_error}", actor=actor)
        await websocket.send_text(f"[Error] {probe_error}\r\n")
        await websocket.close()
        return None
    if probe_error:
        await websocket.send_text(f"[Warn] {probe_error}\r\n")
    if not pkg_manager:
        detail = probe.get("detected_os") or "no recognizable package manager found"
        await websocket.send_text("[Error] Unsupported package manager or system type.\r\n")
        await websocket.send_text(f"[Info] Target system reports: {detail}\r\n")
        await websocket.close()
        return None
    return pkg_manager


async def _remember_host_key(host_ip: str, ssh_port: int, captured: Any) -> None:
    """Store a host key learned on first contact (TOFU)."""
    async with async_session() as db:
        await _persist_captured_host_key(db, host_ip, ssh_port, captured)


class _ClientSink:
    """Output callback for run_ssh_command_stream: forwards to the browser while it is there.

    Awaited per chunk, so output arrives in order and no send task is left behind. If the
    browser goes away mid-run, the update keeps running to completion on the host (aborting
    apt/dnf halfway is worse) and the remaining output is dropped.
    """

    def __init__(self, websocket: WebSocket, device_id: int):
        self.websocket = websocket
        self.device_id = device_id
        self.connected = True

    async def __call__(self, data: str) -> None:
        if not self.connected:
            return
        cleaned = data.replace("\r\n", "\n").replace("\n", "\r\n")
        self.connected = await _send_ws_text(self.websocket, cleaned)
        if not self.connected:
            logger.info("Patch run on device %s: client disconnected, update continues on the host", self.device_id)


async def _report_result(websocket: WebSocket, success: bool, msg: str) -> None:
    if success:
        await _send_ws_text(websocket, "\r\n[Success] Updates completed successfully!\r\n")
    else:
        await _send_ws_text(websocket, f"\r\n[Error] Update failed: {msg}\r\n")
    try:
        await websocket.close()
    except (RuntimeError, OSError) as exc:
        logger.debug("WebSocket close failed in _report_result: %s", exc)


def _session_ssh_options(session_data: dict) -> tuple[dict, dict]:
    """SSH login and the optional host key handling of a consumed patch session.

    Without a pinned key (and outside strict mode) the first connection learns it (TOFU).
    """
    ssh = {key: session_data[key] for key in ("host_ip", "ssh_user", "ssh_password", "ssh_key", "ssh_port")}
    pinned_host_key = session_data.get("pinned_host_key")
    tofu_policy = TofuHostKeyPolicy() if pinned_host_key is None and not settings.ssh_strict_mode else None
    optional = {
        "ssh_key_passphrase": session_data.get("ssh_key_passphrase"),
        "pinned_host_key": pinned_host_key,
        "tofu_policy": tofu_policy,
    }
    return ssh, optional


async def _pin_probed_host_key(ssh: dict, optional: dict) -> None:
    """A host key learned during the probe is stored and pinned for the run itself."""
    tofu_policy = optional["tofu_policy"]
    if tofu_policy and tofu_policy.captured:
        await _remember_host_key(ssh["host_ip"], ssh["ssh_port"], tofu_policy.captured)
        optional["pinned_host_key"] = PinnedHostKey(
            key_type=tofu_policy.captured.key_type, fingerprint=tofu_policy.captured.fingerprint,
        )
        optional["tofu_policy"] = None


async def _announce_update_command(websocket: WebSocket, pkg_manager: str, mode: str) -> str | None:
    """The update command for this package manager, announced to the client; None (socket closed) if unsupported."""
    await websocket.send_text(f"[Info] Detected package manager: {pkg_manager}\r\n")
    cmd = _build_update_command(pkg_manager, mode)
    if cmd is None:
        await websocket.send_text(f"[Error] Package manager {pkg_manager} is not supported.\r\n")
        await websocket.close()
        return None
    if mode == "security-only":
        await websocket.send_text("[Info] Running security updates only...\r\n")
    else:
        await websocket.send_text("[Info] Running full system upgrade...\r\n")
    return cmd


async def _stream_update(params: PatchStreamParams) -> None:
    """Run the update with live output, audit it, and on success keep a learned host key and clear the patch state."""
    sink = _ClientSink(params.websocket, params.device_id)
    stream_fn = _get_agent_attr("run_ssh_command_stream", run_ssh_command_stream)
    stream_kwargs = _ssh_kwargs_for(
        stream_fn,
        {**params.ssh, "command": params.cmd, "output_callback": sink},
        **params.optional,
    )
    success, msg = await stream_fn(**stream_kwargs)
    await audit(
        params.websocket,
        "agent.patches",
        "ok" if success else "failed",
        device_id=params.device_id,
        target=params.ssh["host_ip"],
        detail=params.mode,
        actor=params.actor,
    )

    if success:
        tofu_policy = params.optional.get("tofu_policy")
        if tofu_policy and tofu_policy.captured:
            await _remember_host_key(params.ssh["host_ip"], params.ssh["ssh_port"], tofu_policy.captured)
        clear_fn = _get_agent_attr("_clear_device_patch_state", _clear_device_patch_state)
        await clear_fn(params.device_id)
    if sink.connected:
        await _report_result(params.websocket, success, msg)


@patch_router.websocket("/patches/{device_id}/run-ws")
async def run_patches_websocket(websocket: WebSocket, device_id: int):
    """WebSocket endpoint to run updates and stream output live to the frontend."""
    # Authenticate websocket first (standard browser-session/API-token check)
    from app.api.auth import authenticate_websocket_authorized

    auth_info = await authenticate_websocket_authorized(
        websocket,
        endpoint_type="agent",
        device_id=device_id,
        allowed_levels=("session",),
    )
    if not auth_info:
        return

    await websocket.accept()

    # Validate and consume the one-shot patch session token
    session_data = await _consume_patch_session(websocket, device_id)
    if not session_data:
        await websocket.close(code=4001, reason="Invalid session token")
        return

    mode = session_data["mode"]
    actor = actor_from_identity(auth_info.get("identity"))
    ssh, optional = _session_ssh_options(session_data)

    await websocket.send_text("[Info] Starting update session...\r\n")
    await websocket.send_text("[Info] Detecting target system configuration...\r\n")
    pkg_manager = await _probe_package_manager(websocket, device_id, mode, actor, ssh, optional)
    if pkg_manager is None:
        return

    await _pin_probed_host_key(ssh, optional)
    cmd = await _announce_update_command(websocket, pkg_manager, mode)
    if cmd is None:
        return
    params = PatchStreamParams(
        websocket=websocket,
        device_id=device_id,
        mode=mode,
        actor=actor,
        ssh=ssh,
        optional=optional,
        cmd=cmd,
    )
    await _stream_update(params)
