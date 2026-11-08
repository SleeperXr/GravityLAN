"""The logs API (app/api/logs.py): buffered log lines parsed into fields, newest first, filtered by level."""

import pytest

from app.api import logs
from app.api.logs import parse_log_line


def test_parse_log_line_reads_every_field():
    line = "2026-11-07 23:15:08,645 [WARNING] [cd0171f5-732c] app.api.agent: Agent login: via key"
    assert parse_log_line(line) == {
        "timestamp": "2026-11-07 23:15:08,645",
        "level": "WARNING",
        "correlation_id": "cd0171f5-732c",
        "logger": "app.api.agent",
        # Only the first ": " splits the logger off, the message keeps its own colons
        "message": "Agent login: via key",
    }


def test_parse_log_line_without_a_correlation_id():
    parsed = parse_log_line("2026-11-07 23:13:58,316 [INFO] [-] app.database.migrations: Schema migration complete.")
    assert (parsed["correlation_id"], parsed["level"]) == (None, "INFO")


@pytest.mark.parametrize("line", ["Traceback (most recent call last):", "  File \"/app/x.py\", line 1", ""])
def test_a_line_outside_the_format_is_kept_raw(line):
    assert parse_log_line(line) == {"timestamp": None, "level": "INFO", "correlation_id": None, "logger": "raw", "message": line}


HISTORY = [
    "2026-11-07 10:00:00,000 [INFO] [-] app.a: first",
    "2026-11-07 10:00:01,000 [ERROR] [-] app.b: broke",
    "Traceback (most recent call last):",
    "2026-11-07 10:00:02,000 [INFO] [-] app.a: third",
]


@pytest.fixture
def history(monkeypatch):
    monkeypatch.setattr(logs.log_handler, "get_history", lambda: list(HISTORY))


@pytest.mark.asyncio
async def test_logs_come_newest_first_up_to_the_limit(client, admin_token, history):
    res = await client.get("/api/logs?limit=2", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    assert [e["message"] for e in res.json()] == ["third", "Traceback (most recent call last):"]


@pytest.mark.asyncio
async def test_logs_filter_by_level_in_any_case(client, admin_token, history):
    res = await client.get("/api/logs?level=error", headers={"Authorization": f"Bearer {admin_token}"})
    assert [(e["level"], e["logger"], e["message"]) for e in res.json()] == [("ERROR", "app.b", "broke")]


@pytest.mark.asyncio
async def test_logs_need_an_admin_and_a_sane_limit(client, admin_token, history):
    assert (await client.get("/api/logs")).status_code == 401
    assert (await client.get("/api/logs?limit=0", headers={"Authorization": f"Bearer {admin_token}"})).status_code == 422
