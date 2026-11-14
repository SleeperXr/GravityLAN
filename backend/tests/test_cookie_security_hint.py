"""A session cookie issued over HTTPS without the Secure flag is logged once, and the UI can ask about it."""
import logging

import pytest

from app.api import auth
from app.config import settings as app_config
from app.models.setting import Setting
from app.services.auth_service import hash_password

PASSWORD = "an-admin-password"
WARNING = "Session cookie issued over HTTPS without the Secure flag"


@pytest.fixture(autouse=True)
def fresh_warning(monkeypatch):
    monkeypatch.setattr(auth, "_insecure_cookie_warned", False)
    monkeypatch.setattr(auth, "_dropped_cookie_warned", False)
    monkeypatch.setattr(app_config, "secure_cookies", False)


async def _instance(db) -> None:
    db.add(Setting(key="setup.complete", value="true"))
    db.add(Setting(key="api.master_token", value="sha256:" + "0" * 64))
    db.add(Setting(key="api.admin_password", value=hash_password(PASSWORD)))
    await db.commit()


async def _login(client, proto: str | None = None):
    headers = {"X-Forwarded-Proto": proto} if proto else {}
    return await client.post("/api/auth/login", json={"password": PASSWORD}, headers=headers)


def _warnings(caplog) -> int:
    return sum(WARNING in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


@pytest.mark.asyncio
async def test_login_over_https_warns_once(client, db, caplog):
    await _instance(db)
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        assert (await _login(client, "https")).status_code == 200
        assert (await _login(client, "https")).status_code == 200
    assert _warnings(caplog) == 1


@pytest.mark.asyncio
async def test_login_over_http_does_not_warn(client, db, caplog):
    await _instance(db)
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        assert (await _login(client)).status_code == 200
    assert _warnings(caplog) == 0


@pytest.mark.asyncio
async def test_secure_cookies_set_does_not_warn(client, db, caplog, monkeypatch):
    monkeypatch.setattr(app_config, "secure_cookies", True)
    await _instance(db)
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        await _login(client, "https")
    assert _warnings(caplog) == 0


@pytest.mark.asyncio
async def test_cookie_security_status_needs_a_login(client, db):
    await _instance(db)
    assert (await client.get("/api/auth/cookie-security")).status_code == 401


@pytest.mark.asyncio
async def test_cookie_security_status_reports_flag_and_scheme(client, db):
    await _instance(db)
    await _login(client)
    plain = await client.get("/api/auth/cookie-security")
    assert plain.status_code == 200
    assert plain.json() == {"secure_cookies": False, "https": False}
    proxied = await client.get("/api/auth/cookie-security", headers={"X-Forwarded-Proto": "https"})
    assert proxied.json() == {"secure_cookies": False, "https": True}


DROPPED = "Session cookie issued with the Secure flag over plain HTTP"


@pytest.mark.asyncio
async def test_secure_cookie_over_plain_http_is_named_in_the_answer_and_logged_once(client, db, caplog, monkeypatch):
    """The browser drops a Secure cookie over HTTP: the login screen must say so instead of reappearing."""
    monkeypatch.setattr(app_config, "secure_cookies", True)
    await _instance(db)
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        first = await _login(client)
        await _login(client)
    assert first.status_code == 200 and first.json()["secure_cookie_over_http"] is True
    assert sum(DROPPED in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING) == 1


@pytest.mark.asyncio
async def test_secure_cookie_behind_an_https_proxy_is_fine(client, db, monkeypatch):
    monkeypatch.setattr(app_config, "secure_cookies", True)
    await _instance(db)
    assert (await _login(client, "https")).json()["secure_cookie_over_http"] is False


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "gravitylan.localhost"])
def test_localhost_keeps_secure_cookies_over_http(host, monkeypatch):
    """Browsers store Secure cookies on localhost over HTTP, so no hint there."""
    from types import SimpleNamespace
    monkeypatch.setattr(app_config, "secure_cookies", True)
    request = SimpleNamespace(url=SimpleNamespace(scheme="http", hostname=host), headers={})
    assert auth.secure_cookie_dropped(request) is False
