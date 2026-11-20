"""End-to-end ASGI & Uvicorn server-stack tests for Finding B (transport-peer proxy trust)."""

import logging
from types import SimpleNamespace

import pytest
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import main
from app.api.auth import reject_cross_origin_websocket
from app.services import proxy_hint, proxy_trust


def _build_probe_app() -> FastAPI:
    """Minimal FastAPI app sharing GravityLAN's exact middleware order (TrustedProxyMiddleware outermost)."""
    probe = FastAPI()
    probe.middleware("http")(main.forwarded_for_hint_middleware)
    probe.add_middleware(proxy_trust.TrustedProxyMiddleware)

    @probe.get("/probe")
    async def http_probe(request: Request):
        return {
            "client": request.client.host if request.client else None,
            "scheme": request.url.scheme,
            "transport_peer": getattr(request.state, proxy_trust.STATE_TRANSPORT_PEER, None),
            "from_trusted": getattr(request.state, proxy_trust.STATE_FROM_TRUSTED_PROXY, None),
        }

    @probe.websocket("/ws-probe")
    async def ws_probe(websocket: WebSocket):
        if await reject_cross_origin_websocket(websocket):
            return
        await websocket.accept()
        await websocket.send_json({
            "client": websocket.client.host if websocket.client else None,
            "scheme": websocket.scope.get("scheme"),
            "transport_peer": getattr(websocket.state, proxy_trust.STATE_TRANSPORT_PEER, None),
            "from_trusted": getattr(websocket.state, proxy_trust.STATE_FROM_TRUSTED_PROXY, None),
        })
        await websocket.close()

    return probe


async def _call_http(asgi_app, peer: tuple[str, int] | None, headers: dict[str, str]):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/probe",
        "raw_path": b"/probe",
        "query_string": b"",
        "headers": [(k.lower().encode("latin1"), v.encode("latin1")) for k, v in headers.items()],
        "client": peer,
        "server": ("127.0.0.1", 8000),
    }
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await asgi_app(scope, receive, send)
    import json
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(body)


async def _call_ws(asgi_app, peer: tuple[str, int] | None, headers: dict[str, str]):
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": "/ws-probe",
        "raw_path": b"/ws-probe",
        "query_string": b"",
        "headers": [(k.lower().encode("latin1"), v.encode("latin1")) for k, v in headers.items()],
        "client": peer,
        "server": ("127.0.0.1", 8000),
        "subprotocols": [],
    }
    sent: list[dict] = []
    inbox = [{"type": "websocket.connect"}, {"type": "websocket.disconnect", "code": 1000}]

    async def receive():
        return inbox.pop(0) if inbox else {"type": "websocket.disconnect", "code": 1000}

    async def send(message):
        sent.append(message)

    await asgi_app(scope, receive, send)
    import json
    if any(m["type"] == "websocket.accept" for m in sent):
        payload = next(m["text"] for m in sent if m["type"] == "websocket.send")
        return True, None, json.loads(payload)
    close_msg = next(m for m in sent if m["type"] == "websocket.close")
    return False, close_msg.get("code"), None


@pytest.fixture(autouse=True)
def _reset_proxy_state(monkeypatch):
    monkeypatch.setattr(proxy_hint, "_warned", False)
    monkeypatch.setattr(proxy_trust.settings, "trusted_proxies", "")
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)


def test_uvicorn_config_with_proxy_headers_false_does_not_wrap_app_with_outer_proxy_middleware():
    """Verify the pinned uvicorn.Config(proxy_headers=False) leaves app.main:app as the outer ASGI app."""
    cfg_disabled = uvicorn.Config(main.app, host="127.0.0.1", port=8000, proxy_headers=False)
    cfg_disabled.load()
    assert cfg_disabled.loaded_app is main.app
    assert not isinstance(cfg_disabled.loaded_app, ProxyHeadersMiddleware)

    # Contrast: default proxy_headers=True wraps the app externally, which is why --no-proxy-headers is required
    cfg_default = uvicorn.Config(main.app, host="127.0.0.1", port=8000)
    cfg_default.load()
    assert isinstance(cfg_default.loaded_app, ProxyHeadersMiddleware)

    # TrustedProxyMiddleware must be outermost (index 0) in main.app.user_middleware
    assert main.app.user_middleware[0].cls is proxy_trust.TrustedProxyMiddleware


@pytest.mark.asyncio
async def test_untrusted_peer_spoofing_xff_with_own_ip_cannot_bypass_origin_or_suppress_warning(monkeypatch, caplog):
    """An untrusted peer sending X-Forwarded-For=<own IP> and X-Forwarded-Host=<evil> is refused and warned."""
    monkeypatch.setattr(proxy_trust.settings, "trusted_proxies", "172.18.0.0/16")
    probe = _build_probe_app()
    cfg = uvicorn.Config(probe, host="127.0.0.1", port=8000, proxy_headers=False)
    cfg.load()
    asgi_app = cfg.loaded_app

    spoof_headers = {
        "host": "10.0.0.5:8000",
        "origin": "https://evil.example",
        "x-forwarded-for": "192.168.1.50",
        "x-forwarded-host": "evil.example",
        "x-forwarded-proto": "https",
    }

    accepted, close_code, _ = await _call_ws(asgi_app, ("192.168.1.50", 51234), spoof_headers)
    assert not accepted
    assert close_code == 4003

    with caplog.at_level(logging.WARNING, logger="app.services.proxy_hint"):
        status, body = await _call_http(asgi_app, ("192.168.1.50", 51234), spoof_headers)
    assert status == 200
    assert body == {
        "client": "192.168.1.50",
        "scheme": "http",
        "transport_peer": "192.168.1.50",
        "from_trusted": False,
    }
    proxy_records = [r for r in caplog.records if r.name == "app.services.proxy_hint"]
    assert len(proxy_records) == 1
    assert "192.168.1.50" in proxy_records[0].getMessage()


@pytest.mark.asyncio
async def test_trusted_ipv4_and_ipv6_proxies_and_multihop_chain(monkeypatch, caplog):
    """Trusted IPv4/IPv6 proxies rewrite client/scheme, allow matching XFH, and emit no untrusted warning."""
    monkeypatch.setattr(proxy_trust.settings, "trusted_proxies", "172.18.0.0/16, fd00:10::/64")
    probe = _build_probe_app()
    cfg = uvicorn.Config(probe, host="127.0.0.1", port=8000, proxy_headers=False)
    cfg.load()
    asgi_app = cfg.loaded_app

    # IPv4 trusted proxy with multi-hop chain: client=198.51.100.7 -> proxy2=172.18.0.4 -> proxy1=172.18.0.3
    headers_v4 = {
        "host": "10.0.0.5:8000",
        "origin": "https://gravity.example.com",
        "x-forwarded-for": "198.51.100.7, 172.18.0.4",
        "x-forwarded-host": "gravity.example.com",
        "x-forwarded-proto": "https",
    }
    with caplog.at_level(logging.WARNING, logger="app.services.proxy_hint"):
        status, body = await _call_http(asgi_app, ("172.18.0.3", 40000), headers_v4)
    assert status == 200
    assert body == {
        "client": "198.51.100.7",
        "scheme": "https",
        "transport_peer": "172.18.0.3",
        "from_trusted": True,
    }
    assert caplog.records == []

    accepted, _, ws_body = await _call_ws(asgi_app, ("172.18.0.3", 40001), headers_v4)
    assert accepted
    assert ws_body == {
        "client": "198.51.100.7",
        "scheme": "wss",
        "transport_peer": "172.18.0.3",
        "from_trusted": True,
    }

    # IPv6 trusted proxy
    accepted_v6, _, ws_v6 = await _call_ws(asgi_app, ("fd00:10::5", 40002), {
        "host": "10.0.0.5:8000",
        "origin": "https://gravity.example.com",
        "x-forwarded-for": "2001:db8::99",
        "x-forwarded-host": "gravity.example.com",
        "x-forwarded-proto": "https",
    })
    assert accepted_v6
    assert ws_v6["client"] == "2001:db8::99"
    assert ws_v6["transport_peer"] == "fd00:10::5"
    assert ws_v6["from_trusted"] is True

    # Trusted proxy WITHOUT Forwarded headers: normal Host check still applies
    accepted_no_fwd, _, _ = await _call_ws(asgi_app, ("172.18.0.3", 40003), {
        "host": "gravity.example.com",
        "origin": "https://gravity.example.com",
    })
    assert accepted_no_fwd
    rejected_bad_origin, code_bad, _ = await _call_ws(asgi_app, ("172.18.0.3", 40004), {
        "host": "gravity.example.com",
        "origin": "https://evil.example",
    })
    assert not rejected_bad_origin and code_bad == 4003


@pytest.mark.asyncio
async def test_originless_forwarded_allow_ips_empty_default_and_star(monkeypatch):
    """Test originless clients, default localhost trust, explicit empty FORWARDED_ALLOW_IPS, and '*'."""
    probe = _build_probe_app()
    cfg = uvicorn.Config(probe, host="127.0.0.1", port=8000, proxy_headers=False)
    cfg.load()
    asgi_app = cfg.loaded_app

    # Originless non-browser client is allowed even from untrusted peer
    accepted, _, _ = await _call_ws(asgi_app, ("203.0.113.55", 50000), {"host": "10.0.0.5:8000"})
    assert accepted

    # Default (empty GRAVITYLAN_TRUSTED_PROXIES, no FORWARDED_ALLOW_IPS): 127.0.0.1 and ::1 trusted
    ok_local, _, _ = await _call_ws(asgi_app, ("127.0.0.1", 50001), {
        "host": "127.0.0.1:8000",
        "origin": "https://gravity.example.com",
        "x-forwarded-host": "gravity.example.com",
    })
    assert ok_local

    # Explicit empty FORWARDED_ALLOW_IPS="" trusts nobody, not even 127.0.0.1
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "")
    denied_empty, code_empty, _ = await _call_ws(asgi_app, ("127.0.0.1", 50002), {
        "host": "127.0.0.1:8000",
        "origin": "https://gravity.example.com",
        "x-forwarded-host": "gravity.example.com",
    })
    assert not denied_empty and code_empty == 4003

    # Explicit "*" trusts every peer
    monkeypatch.setattr(proxy_trust.settings, "trusted_proxies", "*")
    ok_star, _, _ = await _call_ws(asgi_app, ("203.0.113.55", 50003), {
        "host": "10.0.0.5:8000",
        "origin": "https://gravity.example.com",
        "x-forwarded-host": "gravity.example.com",
    })
    assert ok_star

    # Typo / non-IP entry trusts no peer; configuring a specific CIDR removes localhost default
    monkeypatch.setattr(proxy_trust.settings, "trusted_proxies", "proxy.local")
    denied_typo, _, _ = await _call_ws(asgi_app, ("127.0.0.1", 50004), {
        "host": "10.0.0.5:8000",
        "origin": "https://gravity.example.com",
        "x-forwarded-host": "gravity.example.com",
    })
    assert not denied_typo

    monkeypatch.setattr(proxy_trust.settings, "trusted_proxies", "172.18.0.0/16")
    denied_local, _, _ = await _call_ws(asgi_app, ("127.0.0.1", 50005), {
        "host": "10.0.0.5:8000",
        "origin": "https://gravity.example.com",
        "x-forwarded-host": "gravity.example.com",
    })
    assert not denied_local


@pytest.mark.asyncio
async def test_lifespan_scope_is_forwarded_unchanged():
    """TrustedProxyMiddleware passes lifespan events straight through without touching scope."""
    seen = []

    async def dummy_app(scope, receive, send):
        seen.append(dict(scope))

    mw = proxy_trust.TrustedProxyMiddleware(dummy_app)
    await mw({"type": "lifespan", "asgi": {"version": "3.0"}}, None, None)
    assert seen == [{"type": "lifespan", "asgi": {"version": "3.0"}}]
