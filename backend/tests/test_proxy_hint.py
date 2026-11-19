"""X-Forwarded-For from an address that is not in GRAVITYLAN_TRUSTED_PROXIES is ignored silently;
GravityLAN now warns once."""
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import proxy_hint


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(proxy_hint, "_warned", False)


@pytest.mark.parametrize("client, header, untrusted", [
    ("10.0.0.2", "203.0.113.7", True),             # proxy not trusted: client stays the proxy
    ("203.0.113.7", "203.0.113.7", False),          # trusted: uvicorn took the address from the header
    ("203.0.113.7", "198.51.100.1, 203.0.113.7", False),
    ("203.0.113.7", "203.0.113.7:51234", False),
    ("2001:db8::7", "[2001:db8::7]:443", False),
    ("2001:db8::7", "2001:db8::7", False),
    ("10.0.0.2", "", False),
    ("10.0.0.2", None, False),
    (None, "203.0.113.7", False),
])
def test_forwarded_by_untrusted(client, header, untrusted):
    assert proxy_hint.forwarded_by_untrusted(client, header) is untrusted


def test_warns_once_per_start(caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.proxy_hint"):
        proxy_hint.check_forwarded_for("10.0.0.2", "203.0.113.7")
        proxy_hint.check_forwarded_for("10.0.0.3", "203.0.113.8")
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "10.0.0.2" in message and "GRAVITYLAN_TRUSTED_PROXIES" in message


def test_no_warning_for_a_trusted_proxy(caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.proxy_hint"):
        proxy_hint.check_forwarded_for("203.0.113.7", "203.0.113.7")
    assert caplog.records == []


def test_the_app_checks_forwarded_requests(monkeypatch):
    from app import main
    seen = []
    monkeypatch.setattr(proxy_hint, "check_forwarded_for", lambda host, header: seen.append((host, header)))
    app = FastAPI()
    app.middleware("http")(main.forwarded_for_hint_middleware)
    app.get("/ping")(lambda: {"ok": True})
    with TestClient(app) as client:
        client.get("/ping")
        client.get("/ping", headers={"X-Forwarded-For": "203.0.113.7"})
    assert seen == [("testclient", "203.0.113.7")]

