#!/usr/bin/env python3
"""Isolated smoke test for a locally built GravityLAN Docker image.

Starts the given image unchanged under ``--network=none`` with a fresh
temporary Docker volume and non-privileged ``PUID``/``PGID``, executes real
HTTP checks inside the container against ``http://127.0.0.1:8000`` using the
image's built-in Python runtime, verifies process UID/GID and persistence across
a container restart, and cleans up only the resources created by this run.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_PUID = 1042
DEFAULT_PGID = 1042
DEFAULT_READY_TIMEOUT = 45.0
DEFAULT_HTTP_TIMEOUT = 10.0
DEFAULT_OVERALL_TIMEOUT = 180.0
POLL_INTERVAL_SECONDS = 0.5
RESTART_STOP_TIMEOUT_SECONDS = 10
LOG_TAIL_LINES = 200

_REDACT_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)\S+"),
    re.compile(r"(?i)((?:set-)?cookie\s*:\s*)[^\r\n]+"),
    re.compile(r"(?i)(gravitylan_token=)[^;\s\r\n]+"),
    re.compile(r"(?i)(token=)[^&\s\r\n]+"),
    re.compile(r"\bsession_[A-Za-z0-9_-]{8,}\b"),
)

# Executed inside the container via `docker exec -i <name> python3 -` with a
# single JSON object on stdin so no synthetic password ever appears in argv.
_CONTAINER_PROBE_SCRIPT = r"""
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(opener, method, path, payload=None, timeout=10.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, dict(exc.headers.items()), body


def _header(headers, name):
    target = name.lower()
    for k, v in headers.items():
        if k.lower() == target:
            return v
    return ""


def _check_health(timeout):
    opener = urllib.request.build_opener(_NoRedirectHandler())
    status, _, body = _open(opener, "GET", "/api/health", timeout=timeout)
    if status != 200:
        raise RuntimeError(f"GET /api/health returned HTTP {status}")
    data = json.loads(body.decode("utf-8"))
    if data.get("status") != "ok":
        raise RuntimeError(f"GET /api/health returned unexpected status payload: {data.get('status')!r}")
    return {"status": data.get("status"), "version": data.get("version")}


def _check_server_process(expected_uid, expected_gid):
    matches = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace")
            if "uvicorn" not in cmdline or "app.main:app" not in cmdline:
                continue
            status_text = (entry / "status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        uid_line = next((ln for ln in status_text.splitlines() if ln.startswith("Uid:")), "")
        gid_line = next((ln for ln in status_text.splitlines() if ln.startswith("Gid:")), "")
        uids = [int(v) for v in uid_line.split()[1:5]]
        gids = [int(v) for v in gid_line.split()[1:5]]
        matches.append({"pid": int(entry.name), "uids": uids, "gids": gids})

    if not matches:
        raise RuntimeError("Could not find running uvicorn app.main:app process in /proc")

    for proc in matches:
        if proc["uids"] != [expected_uid] * 4 or proc["gids"] != [expected_gid] * 4:
            raise RuntimeError(
                f"Server process PID {proc['pid']} runs with Uid={proc['uids']} Gid={proc['gids']}, "
                f"expected Uid={expected_uid} Gid={expected_gid}"
            )

    data_dir = Path(os.environ.get("GRAVITYLAN_DATA_DIR", "/app/data"))
    db_path = data_dir / "gravitylan.db"
    if not db_path.is_file():
        raise RuntimeError(f"Expected SQLite database not found at {db_path}")
    dir_stat = data_dir.stat()
    db_stat = db_path.stat()
    if (dir_stat.st_uid, dir_stat.st_gid) != (expected_uid, expected_gid):
        raise RuntimeError(
            f"{data_dir} is owned by {dir_stat.st_uid}:{dir_stat.st_gid}, expected {expected_uid}:{expected_gid}"
        )
    if (db_stat.st_uid, db_stat.st_gid) != (expected_uid, expected_gid):
        raise RuntimeError(
            f"{db_path} is owned by {db_stat.st_uid}:{db_stat.st_gid}, expected {expected_uid}:{expected_gid}"
        )
    return {
        "server_pids": [m["pid"] for m in matches],
        "uid": expected_uid,
        "gid": expected_gid,
        "db_size": db_stat.st_size,
    }


def _check_ui(timeout):
    opener = urllib.request.build_opener(_NoRedirectHandler())
    redirect_status, headers, _ = _open(opener, "GET", "/", timeout=timeout)
    location = _header(headers, "Location")
    if redirect_status != 307 or location != "/frontend-vue/":
        raise RuntimeError(f"GET / expected 307 -> /frontend-vue/, got HTTP {redirect_status} Location={location!r}")

    ui_status, headers, body = _open(opener, "GET", "/frontend-vue/", timeout=timeout)
    content_type = _header(headers, "Content-Type").lower()
    if ui_status != 200 or "text/html" not in content_type:
        raise RuntimeError(f"GET /frontend-vue/ expected 200 text/html, got HTTP {ui_status} ({content_type!r})")

    html = body.decode("utf-8", errors="replace")
    if "<title>GravityLAN</title>" not in html or 'id="app"' not in html:
        raise RuntimeError("GET /frontend-vue/ did not return expected GravityUI index.html markers")

    asset_matches = re.findall(
        r'''(?:src|href)=["'](/frontend-vue/[^"']+\.(?:js|css)(?:\?[^"']*)?)["']''',
        html,
    )
    if not asset_matches:
        raise RuntimeError("GET /frontend-vue/ index.html references no local JS or CSS asset")

    asset_path = asset_matches[0]
    a_status, a_headers, a_body = _open(opener, "GET", asset_path, timeout=timeout)
    a_type = _header(a_headers, "Content-Type").lower()
    if a_status != 200 or not a_body:
        raise RuntimeError(f"GET {asset_path} expected 200 non-empty asset, got HTTP {a_status} ({len(a_body)} bytes)")
    if "text/html" in a_type:
        raise RuntimeError(f"GET {asset_path} returned text/html fallback instead of a static asset")
    if asset_path.split("?", 1)[0].endswith(".js") and "javascript" not in a_type:
        raise RuntimeError(f"GET {asset_path} returned unexpected Content-Type {a_type!r} for JS asset")
    if asset_path.split("?", 1)[0].endswith(".css") and "css" not in a_type:
        raise RuntimeError(f"GET {asset_path} returned unexpected Content-Type {a_type!r} for CSS asset")

    return {"redirect_status": redirect_status, "redirect_location": location, "asset": asset_path, "asset_bytes": len(a_body)}


def _assert_login_and_protected(password, timeout, check_wrong_password=False):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(_NoRedirectHandler(), urllib.request.HTTPCookieProcessor(jar))

    unauth_status, _, _ = _open(opener, "GET", "/api/auth/me", timeout=timeout)
    if unauth_status != 401:
        raise RuntimeError(f"Unauthenticated GET /api/auth/me expected HTTP 401, got {unauth_status}")

    if check_wrong_password:
        bad_status, _, _ = _open(
            opener,
            "POST",
            "/api/auth/login",
            payload={"password": password + "-wrong"},
            timeout=timeout,
        )
        if bad_status != 401:
            raise RuntimeError(f"Wrong-password login expected HTTP 401, got {bad_status}")

    login_status, _, login_body = _open(
        opener,
        "POST",
        "/api/auth/login",
        payload={"password": password},
        timeout=timeout,
    )
    if login_status != 200:
        raise RuntimeError(f"POST /api/auth/login expected HTTP 200, got {login_status}")
    login_json = json.loads(login_body.decode("utf-8"))
    if login_json.get("status") != "ok":
        raise RuntimeError("POST /api/auth/login did not return status='ok'")

    cookie_names = [c.name for c in jar]
    if "gravitylan_token" not in cookie_names:
        raise RuntimeError("POST /api/auth/login did not set gravitylan_token session cookie")

    me_status, _, me_body = _open(opener, "GET", "/api/auth/me", timeout=timeout)
    if me_status != 200:
        raise RuntimeError(f"Authenticated GET /api/auth/me expected HTTP 200, got {me_status}")
    me_json = json.loads(me_body.decode("utf-8"))
    if me_json.get("scopes") != ["*"]:
        raise RuntimeError(f"Authenticated GET /api/auth/me returned unexpected scopes: {me_json.get('scopes')!r}")

    dev_status, _, dev_body = _open(opener, "GET", "/api/devices", timeout=timeout)
    if dev_status != 200:
        raise RuntimeError(f"Authenticated GET /api/devices expected HTTP 200, got {dev_status}")
    devices = json.loads(dev_body.decode("utf-8"))
    if not isinstance(devices, list):
        raise RuntimeError("Authenticated GET /api/devices did not return a JSON list")

    return {"me_status": me_status, "devices_status": dev_status, "device_count": len(devices)}


def _setup_and_login(password, timeout):
    opener = urllib.request.build_opener(_NoRedirectHandler())
    st_status, _, st_body = _open(opener, "GET", "/api/setup/status", timeout=timeout)
    if st_status != 200:
        raise RuntimeError(f"Pre-setup GET /api/setup/status expected HTTP 200, got {st_status}")
    if json.loads(st_body.decode("utf-8")).get("is_setup_complete") is not False:
        raise RuntimeError("Fresh container unexpectedly reported is_setup_complete=True before setup")

    pre_me_status, _, _ = _open(opener, "GET", "/api/auth/me", timeout=timeout)
    if pre_me_status != 403:
        raise RuntimeError(f"Pre-setup GET /api/auth/me expected HTTP 403, got {pre_me_status}")

    comp_status, _, _ = _open(
        opener,
        "POST",
        "/api/setup/complete",
        payload={"admin_password": password},
        timeout=timeout,
    )
    if comp_status != 200:
        raise RuntimeError(f"POST /api/setup/complete expected HTTP 200, got {comp_status}")

    after_status, _, after_body = _open(opener, "GET", "/api/setup/status", timeout=timeout)
    if after_status != 200 or json.loads(after_body.decode("utf-8")).get("is_setup_complete") is not True:
        raise RuntimeError("Post-setup GET /api/setup/status did not report is_setup_complete=True")

    return _assert_login_and_protected(password, timeout, check_wrong_password=False)


def _post_restart_login(password, timeout):
    opener = urllib.request.build_opener(_NoRedirectHandler())
    st_status, _, st_body = _open(opener, "GET", "/api/setup/status", timeout=timeout)
    if st_status != 200 or json.loads(st_body.decode("utf-8")).get("is_setup_complete") is not True:
        raise RuntimeError("Post-restart GET /api/setup/status did not preserve is_setup_complete=True")
    return _assert_login_and_protected(password, timeout, check_wrong_password=True)


def main():
    req = json.loads(sys.stdin.read())
    action = req["action"]
    timeout = float(req.get("http_timeout", 10.0))
    if action == "health":
        result = _check_health(timeout)
    elif action == "process":
        result = _check_server_process(int(req["puid"]), int(req["pgid"]))
    elif action == "ui":
        result = _check_ui(timeout)
    elif action == "setup_and_login":
        result = _setup_and_login(req["password"], timeout)
    elif action == "post_restart_login":
        result = _post_restart_login(req["password"], timeout)
    else:
        raise RuntimeError(f"Unknown probe action: {action}")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
"""


class SmokeTestError(RuntimeError):
    """Raised when a smoke test check fails."""


def sanitize_text(text: str, secret: str) -> str:
    """Remove synthetic passwords, tokens, and session cookies from diagnostic output."""
    cleaned = text.replace(secret, "[REDACTED]") if secret else text
    for pattern in _REDACT_PATTERNS:
        cleaned = pattern.sub(lambda m: f"{m.group(1)}[REDACTED]" if m.lastindex else "[REDACTED]", cleaned)
    return cleaned


def _remaining_time(deadline: float, cap: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SmokeTestError("Overall smoke-test timeout exceeded")
    return min(remaining, cap)


def _run_docker(
    args: list[str],
    *,
    timeout: float,
    stdin_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", *args]
    try:
        proc = subprocess.run(
            cmd,
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SmokeTestError("Docker CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise SmokeTestError(f"Command timed out after {timeout:.1f}s: docker {' '.join(args[:3])}") from exc

    if check and proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise SmokeTestError(f"docker {' '.join(args[:3])} failed (exit {proc.returncode}): {stderr}")
    return proc


def _inspect_container_state(container_name: str, timeout: float = 10.0) -> dict[str, Any]:
    proc = _run_docker(["inspect", container_name], timeout=timeout, check=False)
    if proc.returncode != 0:
        return {"inspect_error": (proc.stderr or proc.stdout or "").strip()}
    try:
        raw = json.loads(proc.stdout)[0]
    except (ValueError, IndexError, KeyError):
        return {"inspect_error": "Unparseable docker inspect output"}
    state = raw.get("State") or {}
    host_cfg = raw.get("HostConfig") or {}
    return {
        "status": state.get("Status"),
        "running": state.get("Running"),
        "exit_code": state.get("ExitCode"),
        "oom_killed": state.get("OOMKilled"),
        "error": state.get("Error"),
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "restart_count": raw.get("RestartCount"),
        "network_mode": host_cfg.get("NetworkMode"),
    }


def _exec_probe(
    container_name: str,
    payload: dict[str, Any],
    *,
    deadline: float,
    timeout: float,
    secret: str,
) -> dict[str, Any]:
    effective_timeout = _remaining_time(deadline, timeout)
    proc = _run_docker(
        ["exec", "-i", container_name, "python3", "-c", _CONTAINER_PROBE_SCRIPT],
        timeout=effective_timeout,
        stdin_text=json.dumps(payload),
        check=False,
    )
    if proc.returncode != 0:
        detail = sanitize_text((proc.stderr or proc.stdout or "").strip(), secret)
        raise SmokeTestError(f"Probe '{payload['action']}' failed: {detail}")
    try:
        return json.loads(proc.stdout.strip())
    except ValueError as exc:
        raise SmokeTestError(f"Probe '{payload['action']}' returned invalid JSON") from exc


def _wait_for_ready(
    container_name: str,
    *,
    ready_timeout: float,
    http_timeout: float,
    deadline: float,
    secret: str,
) -> dict[str, Any]:
    phase_deadline = min(deadline, time.monotonic() + ready_timeout)
    last_error = "no response yet"
    while time.monotonic() < phase_deadline:
        state = _inspect_container_state(container_name, timeout=_remaining_time(deadline, 10.0))
        status = state.get("status")
        if status in {"exited", "dead"} or state.get("oom_killed"):
            raise SmokeTestError(
                f"Container terminated prematurely before becoming healthy "
                f"(status={status}, exit_code={state.get('exit_code')}, oom_killed={state.get('oom_killed')})"
            )
        try:
            return _exec_probe(
                container_name,
                {"action": "health", "http_timeout": min(http_timeout, 5.0)},
                deadline=phase_deadline,
                timeout=min(http_timeout + 5.0, 15.0),
                secret=secret,
            )
        except SmokeTestError as exc:
            last_error = str(exc)
            time.sleep(POLL_INTERVAL_SECONDS)

    raise SmokeTestError(f"Container did not pass /api/health within {ready_timeout:.1f}s (last error: {last_error})")


def _collect_diagnostics(
    container_name: str,
    *,
    secret: str,
    diagnostics_dir: Path | None,
) -> None:
    try:
        state = _inspect_container_state(container_name, timeout=10.0)
    except (SmokeTestError, OSError, ValueError) as exc:
        state = {"inspect_error": sanitize_text(str(exc), secret)}

    try:
        logs_proc = _run_docker(
            ["logs", "--tail", str(LOG_TAIL_LINES), container_name],
            timeout=15.0,
            check=False,
        )
        combined_logs = "\n".join(part for part in (logs_proc.stdout, logs_proc.stderr) if part)
    except (SmokeTestError, OSError) as exc:
        combined_logs = f"[smoke] Could not collect container logs: {exc}"

    sanitized_logs = sanitize_text(combined_logs, secret)
    status_json = json.dumps(state, indent=2)

    print("\n--- Container Diagnostics (sanitized) ---", file=sys.stderr)
    print(f"Container state:\n{status_json}", file=sys.stderr)
    print(f"Container logs (last {LOG_TAIL_LINES} lines):\n{sanitized_logs}", file=sys.stderr)

    if diagnostics_dir is not None:
        try:
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            (diagnostics_dir / "container-status.json").write_text(status_json + "\n", encoding="utf-8")
            (diagnostics_dir / "container-logs.txt").write_text(sanitized_logs + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"[smoke] Warning: could not write diagnostics to {diagnostics_dir}: {exc}", file=sys.stderr)


def _cleanup_resources(container_name: str, volume_name: str) -> list[str]:
    """Remove only the container and volume created by this run; return any cleanup errors."""
    errors: list[str] = []
    for args, missing_marker in (
        (["rm", "-f", container_name], "no such container"),
        (["volume", "rm", "-f", volume_name], "no such volume"),
    ):
        try:
            proc = _run_docker(args, timeout=20.0, check=False)
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip()
                if missing_marker not in detail.lower():
                    msg = f"docker {' '.join(args)} exited {proc.returncode}: {detail}"
                    print(f"[smoke] Cleanup error: {msg}", file=sys.stderr)
                    errors.append(msg)
        except SmokeTestError as exc:
            msg = f"docker {' '.join(args)} failed: {exc}"
            print(f"[smoke] Cleanup error: {msg}", file=sys.stderr)
            errors.append(msg)
    return errors


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an isolated smoke test against a local GravityLAN Docker image.")
    parser.add_argument("image", help="Local Docker image reference to test (e.g. gravitylan:ci)")
    parser.add_argument("--puid", type=int, default=DEFAULT_PUID, help=f"Non-root PUID (default: {DEFAULT_PUID})")
    parser.add_argument("--pgid", type=int, default=DEFAULT_PGID, help=f"Non-root PGID (default: {DEFAULT_PGID})")
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=DEFAULT_READY_TIMEOUT,
        help=f"Seconds to wait for /api/health readiness (default: {DEFAULT_READY_TIMEOUT})",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=DEFAULT_HTTP_TIMEOUT,
        help=f"Per-request HTTP timeout in seconds (default: {DEFAULT_HTTP_TIMEOUT})",
    )
    parser.add_argument(
        "--overall-timeout",
        type=float,
        default=DEFAULT_OVERALL_TIMEOUT,
        help=f"Total smoke-test timeout in seconds (default: {DEFAULT_OVERALL_TIMEOUT})",
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=Path,
        default=None,
        help="Optional directory to write sanitized diagnostics on failure",
    )
    args = parser.parse_args(argv)
    if args.puid <= 0 or args.pgid <= 0:
        parser.error("--puid and --pgid must be positive non-root IDs")
    return args


def run_smoke_test(args: argparse.Namespace) -> int:
    run_id = uuid.uuid4().hex[:12]
    container_name = f"gravitylan-smoke-{run_id}"
    volume_name = f"gravitylan-smoke-data-{run_id}"
    synthetic_password = f"smoke-{secrets.token_urlsafe(18)}"
    deadline = time.monotonic() + args.overall_timeout

    interrupted_signal: list[int] = []

    def _handle_signal(signum: int, _frame: Any) -> None:
        interrupted_signal.append(signum)
        raise KeyboardInterrupt(f"Received signal {signum}")

    previous_handlers: dict[int, Any] = {}
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, _handle_signal)

    created_any = False
    exit_code = 0
    try:
        # Verify the local image exists before creating any test resources.
        _run_docker(["image", "inspect", args.image], timeout=_remaining_time(deadline, 15.0))

        created_any = True
        print(f"[smoke] Creating isolated volume {volume_name}")
        _run_docker(["volume", "create", volume_name], timeout=_remaining_time(deadline, 15.0))

        print(f"[smoke] Starting container {container_name} from {args.image} (--network=none, PUID={args.puid}, PGID={args.pgid})")
        _run_docker(
            [
                "run",
                "-d",
                "--name",
                container_name,
                "--network=none",
                "-v",
                f"{volume_name}:/app/data",
                "-e",
                f"PUID={args.puid}",
                "-e",
                f"PGID={args.pgid}",
                "-e",
                "GRAVITYLAN_SECURE_COOKIES=false",
                args.image,
            ],
            timeout=_remaining_time(deadline, 30.0),
        )

        health = _wait_for_ready(
            container_name,
            ready_timeout=args.ready_timeout,
            http_timeout=args.http_timeout,
            deadline=deadline,
            secret=synthetic_password,
        )
        print(f"[smoke] 1/7 Health ready: status={health['status']} version={health.get('version')}")

        proc_info = _exec_probe(
            container_name,
            {"action": "process", "puid": args.puid, "pgid": args.pgid},
            deadline=deadline,
            timeout=15.0,
            secret=synthetic_password,
        )
        print(
            f"[smoke] 2/7 Server process verified: pids={proc_info['server_pids']} "
            f"uid={proc_info['uid']} gid={proc_info['gid']} db_size={proc_info['db_size']}"
        )

        ui_info = _exec_probe(
            container_name,
            {"action": "ui", "http_timeout": args.http_timeout},
            deadline=deadline,
            timeout=args.http_timeout + 10.0,
            secret=synthetic_password,
        )
        print(
            f"[smoke] 3/7 GravityUI verified: GET / -> {ui_info['redirect_status']} {ui_info['redirect_location']}, "
            f"asset {ui_info['asset']} ({ui_info['asset_bytes']} bytes)"
        )

        setup_info = _exec_probe(
            container_name,
            {"action": "setup_and_login", "password": synthetic_password, "http_timeout": args.http_timeout},
            deadline=deadline,
            timeout=args.http_timeout * 4 + 15.0,
            secret=synthetic_password,
        )
        print(
            f"[smoke] 4/7 Setup + initial login verified: /api/auth/me={setup_info['me_status']} "
            f"/api/devices={setup_info['devices_status']}"
        )

        print(f"[smoke] 5/7 Restarting container {container_name} with the same volume {volume_name}")
        _run_docker(
            ["restart", "-t", str(RESTART_STOP_TIMEOUT_SECONDS), container_name],
            timeout=_remaining_time(deadline, 30.0),
        )

        health_after = _wait_for_ready(
            container_name,
            ready_timeout=args.ready_timeout,
            http_timeout=args.http_timeout,
            deadline=deadline,
            secret=synthetic_password,
        )
        proc_after = _exec_probe(
            container_name,
            {"action": "process", "puid": args.puid, "pgid": args.pgid},
            deadline=deadline,
            timeout=15.0,
            secret=synthetic_password,
        )
        print(
            f"[smoke] 6/7 Restarted container ready: status={health_after['status']} "
            f"pids={proc_after['server_pids']} uid={proc_after['uid']} gid={proc_after['gid']}"
        )

        restart_info = _exec_probe(
            container_name,
            {"action": "post_restart_login", "password": synthetic_password, "http_timeout": args.http_timeout},
            deadline=deadline,
            timeout=args.http_timeout * 4 + 15.0,
            secret=synthetic_password,
        )
        print(
            f"[smoke] 7/7 Post-restart persistence & fresh login verified: "
            f"/api/auth/me={restart_info['me_status']} /api/devices={restart_info['devices_status']}"
        )

    except KeyboardInterrupt as exc:
        print(f"[smoke] ABORTED: {exc}", file=sys.stderr)
        if created_any:
            _collect_diagnostics(container_name, secret=synthetic_password, diagnostics_dir=args.diagnostics_dir)
        exit_code = 128 + interrupted_signal[0] if interrupted_signal else 130
    except SmokeTestError as exc:
        print(f"[smoke] FAIL: {sanitize_text(str(exc), synthetic_password)}", file=sys.stderr)
        if created_any:
            _collect_diagnostics(container_name, secret=synthetic_password, diagnostics_dir=args.diagnostics_dir)
        exit_code = 1
    except Exception as exc:  # noqa: BLE001 — top-level CLI boundary to ensure diagnostics and cleanup run
        print(f"[smoke] UNEXPECTED ERROR: {sanitize_text(str(exc), synthetic_password)}", file=sys.stderr)
        if created_any:
            _collect_diagnostics(container_name, secret=synthetic_password, diagnostics_dir=args.diagnostics_dir)
        exit_code = 1
    finally:
        cleanup_errors: list[str] = []
        if created_any:
            cleanup_errors = _cleanup_resources(container_name, volume_name)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)

    if cleanup_errors and exit_code == 0:
        print("[smoke] FAIL: Smoke checks passed, but cleanup left test resources behind.", file=sys.stderr)
        return 1
    if exit_code == 0:
        print("[smoke] PASS: Container smoke test completed successfully.")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    return run_smoke_test(_parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
