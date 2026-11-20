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
def test_dockerfile_disables_outer_uvicorn_proxy_headers(tmp_path):
    _, args = _run(tmp_path)
    tokens = args.split()
    assert "--no-proxy-headers" in tokens
    assert "--proxy-headers" not in tokens


def test_the_setting_is_a_known_option(monkeypatch):
    """An .env file with the variable must not fail the settings validation."""
    monkeypatch.setenv("GRAVITYLAN_TRUSTED_PROXIES", "172.18.0.0/16")
    assert Settings().trusted_proxies == "172.18.0.0/16"


def test_effective_trusted_proxies_precedence_and_parsing(monkeypatch):
    from app.services import proxy_trust

    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    monkeypatch.setattr(proxy_trust.settings, "trusted_proxies", "")
    assert proxy_trust.effective_trusted_proxies_raw() == "127.0.0.1,::1"

    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.2, fd00::/64")
    assert proxy_trust.effective_trusted_proxies_raw() == "10.0.0.2, fd00::/64"

    # Explicit empty FORWARDED_ALLOW_IPS must be preserved (trusts nothing)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "")
    assert proxy_trust.effective_trusted_proxies_raw() == ""
    assert proxy_trust.parse_trusted_proxy_networks("") == ()
    assert not proxy_trust.is_trusted_proxy_peer("127.0.0.1", ())

    # GRAVITYLAN_TRUSTED_PROXIES wins over FORWARDED_ALLOW_IPS
    monkeypatch.setattr(proxy_trust.settings, "trusted_proxies", "172.18.0.0/16")
    assert proxy_trust.effective_trusted_proxies_raw() == "172.18.0.0/16"

    # Invalid entries never widen trust; "*" is explicit
    assert proxy_trust.parse_trusted_proxy_networks("not-an-ip, 999.999.999.999") == ()
    assert proxy_trust.parse_trusted_proxy_networks("*") is None
    assert proxy_trust.is_trusted_proxy_peer("203.0.113.9", None) is True
