"""Regression tests for scripts/smoke_container.py process matching, redaction, and redirect handling."""

from __future__ import annotations

import http.server
import importlib.util
import os
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_smoke_module() -> Any:
    spec = importlib.util.spec_from_file_location("smoke_container", ROOT / "scripts" / "smoke_container.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_probe_namespace(smoke_module: Any) -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    exec(compile(smoke_module._CONTAINER_PROBE_SCRIPT, "<container_probe>", "exec"), namespace)  # noqa: S102 — static probe source under test
    return namespace


def _write_fake_proc_entry(
    proc_root: Path,
    pid: int,
    argv: list[str],
    uids: tuple[int, int, int, int],
    gids: tuple[int, int, int, int],
) -> None:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True, exist_ok=True)
    raw_cmdline = b"\x00".join(part.encode("utf-8") for part in argv) + b"\x00"
    (pid_dir / "cmdline").write_bytes(raw_cmdline)
    uid_str = "\t".join(str(v) for v in uids)
    gid_str = "\t".join(str(v) for v in gids)
    (pid_dir / "status").write_text(
        f"Name:\tpython\nPid:\t{pid}\nUid:\t{uid_str}\nGid:\t{gid_str}\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def smoke_module() -> Any:
    return _load_smoke_module()


@pytest.fixture(scope="module")
def probe_ns(smoke_module: Any) -> dict[str, Any]:
    return _load_probe_namespace(smoke_module)


@pytest.mark.parametrize(
    "argv",
    [
        ["/opt/venv/bin/python", "/opt/venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
        ["/opt/venv/bin/python3.12", "/opt/venv/bin/uvicorn", "app.main:app", "--workers", "1"],
        ["/opt/venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0"],
        ["uvicorn", "app.main:app"],
        ["python3", "-m", "uvicorn", "app.main:app", "--no-proxy-headers"],
    ],
)
def test_uvicorn_server_argv_recognized(probe_ns: dict[str, Any], argv: list[str]) -> None:
    assert probe_ns["_is_uvicorn_server_argv"](argv) is True


def test_python_c_probe_script_is_not_recognized_as_server(smoke_module: Any, probe_ns: dict[str, Any]) -> None:
    argv = ["python3", "-c", smoke_module._CONTAINER_PROBE_SCRIPT]
    assert "uvicorn" in smoke_module._CONTAINER_PROBE_SCRIPT
    assert "app.main:app" in smoke_module._CONTAINER_PROBE_SCRIPT
    assert probe_ns["_is_uvicorn_server_argv"](argv) is False


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["/opt/venv/bin/python", "/opt/venv/bin/uvicorn", "app.main:app2"],
        ["/opt/venv/bin/python", "/opt/venv/bin/uvicorn", "--app=app.main:app"],
        ["/opt/venv/bin/python", "/opt/venv/bin/uvicorn-wrapper", "app.main:app"],
        ["/opt/venv/bin/python", "-m", "uvicorn_fake", "app.main:app"],
        ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0"],
        ["/usr/bin/env", "uvicorn", "app.main:app"],
    ],
)
def test_similar_but_non_matching_argv_rejected(probe_ns: dict[str, Any], argv: list[str]) -> None:
    assert probe_ns["_is_uvicorn_server_argv"](argv) is False


def test_check_server_process_fails_when_no_server_found(
    smoke_module: Any,
    probe_ns: dict[str, Any],
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    # Only a python -c probe process (as root) and a shell exist, no real uvicorn server.
    _write_fake_proc_entry(proc_root, 54, ["python3", "-c", smoke_module._CONTAINER_PROBE_SCRIPT], (0, 0, 0, 0), (0, 0, 0, 0))
    _write_fake_proc_entry(proc_root, 1, ["sh", "-c", "sleep 10"], (1042, 1042, 1042, 1042), (1042, 1042, 1042, 1042))

    with pytest.raises(RuntimeError, match="Could not find running uvicorn app.main:app process"):
        probe_ns["_check_server_process"](1042, 1042, proc_root=str(proc_root), data_dir=str(tmp_path))


def test_check_server_process_excludes_own_pid(probe_ns: dict[str, Any], tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    # Even if our own PID had a matching argv, os.getpid() must be excluded.
    _write_fake_proc_entry(
        proc_root,
        os.getpid(),
        ["/opt/venv/bin/python", "/opt/venv/bin/uvicorn", "app.main:app"],
        (1042, 1042, 1042, 1042),
        (1042, 1042, 1042, 1042),
    )

    with pytest.raises(RuntimeError, match="Could not find running uvicorn app.main:app process"):
        probe_ns["_check_server_process"](1042, 1042, proc_root=str(proc_root), data_dir=str(tmp_path))


@pytest.mark.parametrize(
    ("uids", "gids"),
    [
        ((0, 0, 0, 0), (0, 0, 0, 0)),
        ((1042, 0, 1042, 1042), (1042, 1042, 1042, 1042)),
        ((1042, 1042, 1042, 1042), (1042, 1042, 0, 1042)),
        ((1000, 1000, 1000, 1000), (1000, 1000, 1000, 1000)),
    ],
)
def test_check_server_process_rejects_wrong_uid_or_gid(
    probe_ns: dict[str, Any],
    tmp_path: Path,
    uids: tuple[int, int, int, int],
    gids: tuple[int, int, int, int],
) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    # A vanished candidate (directory without cmdline) must be skipped cleanly.
    (proc_root / "99999").mkdir()
    _write_fake_proc_entry(
        proc_root,
        1,
        ["/opt/venv/bin/python", "/opt/venv/bin/uvicorn", "app.main:app", "--workers", "1"],
        uids,
        gids,
    )

    with pytest.raises(RuntimeError, match="expected Uid=1042 Gid=1042"):
        probe_ns["_check_server_process"](1042, 1042, proc_root=str(proc_root), data_dir=str(tmp_path))


def test_sanitize_text_redacts_secrets_and_cookies(smoke_module: Any) -> None:
    raw = (
        "Set-Cookie: gravitylan_token=secret_cookie_val; HttpOnly\n"
        "Authorization: Bearer topsecret_token\n"
        "session_abcdefgh123456 pw=my-synth-pass"
    )
    cleaned = smoke_module.sanitize_text(raw, "my-synth-pass")
    assert "my-synth-pass" not in cleaned
    assert "secret_cookie_val" not in cleaned
    assert "topsecret_token" not in cleaned
    assert "session_abcdefgh123456" not in cleaned


def test_no_redirect_handler_captures_307_without_following(probe_ns: dict[str, Any]) -> None:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(307)
            self.send_header("Location", "/frontend-vue/")
            self.end_headers()

        def log_message(self, *_args: Any) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_base = probe_ns["BASE_URL"]
    try:
        probe_ns["BASE_URL"] = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(probe_ns["_NoRedirectHandler"]())
        status, headers, _ = probe_ns["_open"](opener, "GET", "/", timeout=5.0)
    finally:
        probe_ns["BASE_URL"] = original_base
        server.shutdown()
        server.server_close()

    assert status == 307
    assert probe_ns["_header"](headers, "Location") == "/frontend-vue/"
