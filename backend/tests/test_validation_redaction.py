"""The 422 handler must not log or echo the submitted values (passwords, secrets)."""

import json
import logging

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError
from starlette.requests import Request

from app.main import validation_exception_handler

SECRET = "hunter2-router-secret"


class _Body(BaseModel):
    password: str = Field(min_length=32)


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/auth/password", "headers": [], "query_string": b""})


@pytest.mark.asyncio
async def test_validation_errors_leave_out_the_submitted_value(caplog):
    try:
        _Body(password=SECRET)
    except ValidationError as err:
        exc = RequestValidationError(err.errors())

    with caplog.at_level(logging.ERROR):
        response = await validation_exception_handler(_request(), exc)

    body = json.loads(response.body)
    assert response.status_code == 422
    assert body["detail"][0]["loc"] == ["password"]
    assert body["detail"][0]["type"] == "string_too_short"
    assert "input" not in body["detail"][0]
    assert SECRET not in response.body.decode()
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_dns_server_validator_error_does_not_quote_the_value(caplog):
    """normalize_dns_server's message reaches msg and ctx["error"]; neither may carry the value."""
    from app.schemas.network import SubnetCreate

    try:
        SubnetCreate(name="LAN", cidr="192.168.1.0/24", dns_server=SECRET)
    except ValidationError as err:
        exc = RequestValidationError(err.errors())

    with caplog.at_level(logging.ERROR):
        response = await validation_exception_handler(_request(), exc)

    body = json.loads(response.body)
    assert body["detail"][0]["loc"] == ["dns_server"]
    assert "Invalid DNS server" in body["detail"][0]["msg"]
    assert "error" not in body["detail"][0].get("ctx", {})
    assert SECRET not in response.body.decode()
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_other_ctx_values_stay():
    try:
        _Body(password="short")
    except ValidationError as err:
        exc = RequestValidationError(err.errors())

    body = json.loads((await validation_exception_handler(_request(), exc)).body)
    assert body["detail"][0]["ctx"] == {"min_length": 32}
