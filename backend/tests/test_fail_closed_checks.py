"""Checks that must refuse when they cannot tell: webhook deliveries without a readable HTTP status and
the agent version check without a diff to look at."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import webhook_service as ws

ROOT = Path(__file__).resolve().parents[2]


def _entry():
    return SimpleNamespace(attempts=0, max_attempts=3, status="pending", last_error=None, next_attempt_at=None,
                           event_type="device.offline")


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    SimpleNamespace(text="ok"),                      # no status at all
    SimpleNamespace(status_code="200", text="ok"),   # not a number
    SimpleNamespace(status_code=None, text=""),
])
async def test_a_response_without_a_readable_status_is_no_delivery(monkeypatch, response):
    async def post(client, url, body, headers=None):
        return response

    monkeypatch.setattr(ws, "_send_webhook_post", post)
    entry = _entry()
    assert await ws._execute_and_record_delivery(None, "http://192.0.2.5/hook", {}, {}, entry) is False
    assert entry.attempts == 1 and entry.last_error.startswith("HTTP ")


@pytest.mark.asyncio
@pytest.mark.parametrize("code, delivered", [(200, True), (302, True), (404, False), (500, False)])
async def test_a_real_status_decides(monkeypatch, code, delivered):
    async def post(client, url, body, headers=None):
        return SimpleNamespace(status_code=code, text="")

    monkeypatch.setattr(ws, "_send_webhook_post", post)
    assert await ws._execute_and_record_delivery(None, "http://192.0.2.5/hook", {}, {}, _entry()) is delivered


def test_agent_version_check_fails_without_a_diffable_base():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_agent_version.py"), "no-such-ref-0000"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "cannot be diffed" in result.stderr
