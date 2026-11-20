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


@pytest.mark.parametrize("client, header, from_trusted, untrusted", [
    ("10.0.0.2", "203.0.113.7", False, True),
    # Even when an untrusted peer puts its own IP in X-Forwarded-For, it must still be flagged untrusted
    ("192.168.1.50", "192.168.1.50", False, True),
    ("172.18.0.3", "203.0.113.7", True, False),
    ("172.18.0.3", "198.51.100.1, 172.18.0.4", True, False),
    ("2001:db8::1", "[2001:db8::7]:443", True, False),
    ("10.0.0.2", "", False, False),
    ("10.0.0.2", None, False, False),
    (None, "203.0.113.7", False, False),
])
def test_forwarded_by_untrusted(client, header, from_trusted, untrusted):
    assert proxy_hint.forwarded_by_untrusted(client, header, from_trusted_proxy=from_trusted) is untrusted


def test_warns_once_per_start(caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.proxy_hint"):
        proxy_hint.check_forwarded_for("10.0.0.2", "203.0.113.7", from_trusted_proxy=False)
        proxy_hint.check_forwarded_for("10.0.0.3", "203.0.113.8", from_trusted_proxy=False)
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "10.0.0.2" in message and "GRAVITYLAN_TRUSTED_PROXIES" in message


def test_no_warning_for_a_trusted_proxy(caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.proxy_hint"):
        proxy_hint.check_forwarded_for("172.18.0.3", "203.0.113.7", from_trusted_proxy=True)
    assert caplog.records == []


def test_the_app_checks_forwarded_requests(monkeypatch):
    from app import main
    seen = []
    monkeypatch.setattr(
        proxy_hint,
        "check_forwarded_for",
        lambda host, header, **kw: seen.append((host, header, kw.get("from_trusted_proxy"))),
    )
    app = FastAPI()
    app.middleware("http")(main.forwarded_for_hint_middleware)
    app.get("/ping")(lambda: {"ok": True})
    with TestClient(app) as client:
        client.get("/ping")
        client.get("/ping", headers={"X-Forwarded-For": "203.0.113.7"})
    assert seen == [("testclient", "203.0.113.7", None)]

