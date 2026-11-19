"""GRAVITYLAN_TRUSTED_PROXIES reaches uvicorn as FORWARDED_ALLOW_IPS (client IP behind a reverse proxy)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def _start_command() -> str:
    line = next(l for l in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines() if l.startswith("CMD "))
    argv = json.loads(line[len("CMD "):])
    assert argv[:2] == ["sh", "-c"]
    return argv[2]


def _run(tmp_path, **env) -> list[str]:
    """Run the container's start command with a stub uvicorn; return what the stub saw."""
    stub = tmp_path / "uvicorn"
    stub.write_text('#!/bin/sh\necho "$FORWARDED_ALLOW_IPS"\necho "$@"\n')
    stub.chmod(0o755)
    clean = {k: v for k, v in os.environ.items() if k not in ("GRAVITYLAN_TRUSTED_PROXIES", "FORWARDED_ALLOW_IPS")}
    out = subprocess.run(
        ["sh", "-c", _start_command()], env={**clean, "PATH": f"{tmp_path}:{os.environ['PATH']}", **env},
        capture_output=True, text=True, check=True,
    )
    return out.stdout.splitlines()


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_without_the_setting_only_localhost_may_forward(tmp_path):
    allowed, args = _run(tmp_path)
    assert allowed == "127.0.0.1,::1"
    assert "--proxy-headers" in args.split()


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_the_setting_names_the_trusted_proxies(tmp_path):
    allowed, _ = _run(tmp_path, GRAVITYLAN_TRUSTED_PROXIES="172.18.0.0/16,10.0.0.2")
    assert allowed == "172.18.0.0/16,10.0.0.2"


def test_the_setting_is_a_known_option(monkeypatch):
    """An .env file with the variable must not fail the settings validation."""
    monkeypatch.setenv("GRAVITYLAN_TRUSTED_PROXIES", "172.18.0.0/16")
    assert Settings().trusted_proxies == "172.18.0.0/16"
