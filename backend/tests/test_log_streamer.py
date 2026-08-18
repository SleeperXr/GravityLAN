"""Tests for the log streaming handler (app/services/log_streamer.py)."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.log_streamer import (
    CorrelationIdFilter,
    LogStreamerHandler,
    SafeCorrelationIdFormatter,
    apply_log_level,
    correlation_id_ctx,
    log_handler,
)


# --- CorrelationIdFilter ----------------------------------------------------

def test_correlation_id_filter_injects_id():
    filt = CorrelationIdFilter()
    token = correlation_id_ctx.set("abc-123")
    try:
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", (), None)
        assert filt.filter(record) is True
        assert record.correlation_id == "abc-123"
    finally:
        correlation_id_ctx.reset(token)


def test_correlation_id_filter_default():
    filt = CorrelationIdFilter()
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", (), None)
    assert filt.filter(record) is True
    assert record.correlation_id == "-"


# --- SafeCorrelationIdFormatter ---------------------------------------------

def test_formatter_defaults_missing_correlation_id():
    formatter = SafeCorrelationIdFormatter("%(correlation_id)s")
    # Fresh record without correlation_id attribute
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", (), None)
    assert formatter.format(record) == "-"


# --- LogStreamerHandler -----------------------------------------------------

def test_handler_buffers_messages():
    handler = LogStreamerHandler(capacity=3)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for i in range(5):
        handler.emit(logging.LogRecord("t", logging.INFO, __file__, 1, f"msg{i}", (), None))
    assert handler.get_history() == ["msg2", "msg3", "msg4"]  # ring buffer


def test_handler_no_loop_no_crash():
    handler = LogStreamerHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    ws = MagicMock()
    handler.subscribers.add(ws)
    handler._loop = None  # no running loop context
    handler.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "hi", (), None))
    # Should not raise; no broadcast scheduled
    assert "hi" in handler.get_history()


@pytest.mark.asyncio
async def test_handler_broadcast_removes_dead_links():
    handler = LogStreamerHandler()
    ws_alive = MagicMock()
    ws_alive.send_text = AsyncMock()
    ws_dead = MagicMock()
    ws_dead.send_text = AsyncMock(side_effect=RuntimeError("gone"))
    handler.subscribers.update({ws_alive, ws_dead})

    await handler._broadcast("hello")
    assert ws_alive.send_text.await_count == 1
    assert ws_dead.send_text.await_count == 1
    assert handler.subscribers == {ws_alive}


@pytest.mark.asyncio
async def test_handler_broadcast_empty():
    handler = LogStreamerHandler()
    await handler._broadcast("hello")  # no subscribers, must not raise


def test_handler_subscribe_unsubscribe():
    handler = LogStreamerHandler()
    ws = MagicMock()
    handler.subscribe(ws)
    assert ws in handler.subscribers
    handler.unsubscribe(ws)
    assert ws not in handler.subscribers
    handler.unsubscribe(ws)  # idempotent


# --- apply_log_level --------------------------------------------------------

def test_apply_log_level_info():
    # Use real loggers and restore levels afterwards
    root = logging.getLogger()
    app_logger = logging.getLogger("app")
    sql_logger = logging.getLogger("sqlalchemy.engine")
    sqlite_logger = logging.getLogger("aiosqlite")

    saved = (root.level, app_logger.level, sql_logger.level, sqlite_logger.level)
    try:
        apply_log_level("INFO")
        assert root.level == logging.INFO
        apply_log_level("debug_sql")
        assert root.level == logging.DEBUG
        apply_log_level("bogus")  # falls back to INFO
        assert root.level == logging.INFO
    finally:
        root.setLevel(saved[0])
        app_logger.setLevel(saved[1])
        sql_logger.setLevel(saved[2])
        sqlite_logger.setLevel(saved[3])


# --- global instance --------------------------------------------------------

def test_global_handler_configured():
    assert isinstance(log_handler, LogStreamerHandler)
    assert len(log_handler.filters) == 1
    assert log_handler.formatter is not None
