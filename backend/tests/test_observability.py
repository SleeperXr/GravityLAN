import pytest
import logging
from unittest.mock import MagicMock
from app.exceptions import GravityLANError
from app.services.log_streamer import CorrelationIdFilter, correlation_id_ctx
from app.main import PollingFilter, gravitylan_exception_handler

@pytest.mark.asyncio
async def test_correlation_id_middleware(client):
    """Verify that requests automatically receive a correlation ID and return it in headers."""
    # 1. Test auto-generation of Correlation ID
    response = await client.get("/")
    assert response.status_code == 200
    assert "X-Correlation-ID" in response.headers
    assert len(response.headers["X-Correlation-ID"]) > 0

    # 2. Test propagation of user-supplied Correlation ID
    custom_cid = "custom-test-correlation-id-123"
    response = await client.get("/", headers={"X-Correlation-ID": custom_cid})
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == custom_cid


@pytest.mark.asyncio
async def test_exception_correlation_id(client):
    """Verify that custom, validation, and universal exceptions return correlation_id."""
    # 1. RequestValidationError (422) trigger (POST /api/auth/login with invalid json)
    response = await client.post("/api/auth/login", json={"password": None})
    assert response.status_code == 422
    data = response.json()
    assert "correlation_id" in data
    assert "X-Correlation-ID" in response.headers
    assert data["correlation_id"] == response.headers["X-Correlation-ID"]

    # 2. Test the GravityLANError handler directly using a dummy Request
    from fastapi import Request
    mock_request = MagicMock(spec=Request)
    mock_request.url.path = "/test-path"
    
    exc = GravityLANError("Test application error", status_code=400)
    token = correlation_id_ctx.set("test-cid-val")
    try:
        resp = await gravitylan_exception_handler(mock_request, exc)
        assert resp.status_code == 400
        assert resp.headers["X-Correlation-ID"] == "test-cid-val"
        
        # Decode body
        import json
        payload = json.loads(resp.body.decode())
        assert payload["correlation_id"] == "test-cid-val"
        assert payload["message"] == "Test application error"
    finally:
        correlation_id_ctx.reset(token)


def test_correlation_id_filter():
    """Verify that CorrelationIdFilter successfully injects correlation_id into records."""
    filt = CorrelationIdFilter()
    record = logging.LogRecord("test_logger", logging.INFO, "pathname", 10, "message", (), None)
    
    token = correlation_id_ctx.set("test-filter-cid")
    try:
        assert filt.filter(record) is True
        assert record.correlation_id == "test-filter-cid"
    finally:
        correlation_id_ctx.reset(token)


def test_polling_filter():
    """Verify that PollingFilter suppresses successful uvicorn logs but allows error access logs."""
    polling_filter = PollingFilter()

    # Helper to construct a mock log record using template formatting
    def make_record(template: str, args: tuple = ()):
        rec = logging.LogRecord("uvicorn.access", logging.INFO, "pathname", 10, template, args, None)
        return rec

    # Standard Uvicorn access template: '%s - "%s %s HTTP/%s" %d'
    template = '%s - "%s %s HTTP/%s" %d'

    # 1. Success access log of a polling endpoint -> Should be suppressed (return False)
    rec1 = make_record(
        template,
        ("127.0.0.1:12345", "GET", "/api/health", "1.1", 200)
    )
    assert polling_filter.filter(rec1) is False

    # 2. Error access log of a polling endpoint (e.g. 500 status) -> Should NOT be suppressed (return True)
    rec2 = make_record(
        template,
        ("127.0.0.1:12345", "GET", "/api/health", "1.1", 500)
    )
    assert polling_filter.filter(rec2) is True

    # 3. Error access log with fallback message check (e.g. 404 in msg but args empty) -> Should NOT be suppressed (return True)
    rec3 = make_record(
        '127.0.0.1:12345 - "GET /api/health HTTP/1.1" 404',
        ()
    )
    assert polling_filter.filter(rec3) is True

    # 4. Success access log of a non-polling endpoint -> Should NOT be suppressed (return True)
    rec4 = make_record(
        template,
        ("127.0.0.1:12345", "GET", "/api/some-custom-route", "1.1", 200)
    )
    assert polling_filter.filter(rec4) is True


@pytest.mark.asyncio
async def test_log_streamer_lazy_loop():
    """Verify that LogStreamerHandler initializes its loop lazily on subscription or emit."""
    from app.services.log_streamer import LogStreamerHandler
    from unittest.mock import MagicMock
    
    # 1. On creation, loop should be None
    handler = LogStreamerHandler(capacity=5)
    assert handler._loop is None

    # 2. On subscribe, loop should be lazily resolved to the active running loop
    mock_ws = MagicMock()
    handler.subscribe(mock_ws)
    assert handler._loop is not None
