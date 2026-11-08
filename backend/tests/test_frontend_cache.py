"""GravityUI is the only interface: `/` and old classic-view addresses lead to it, and its
index.html is never cached (otherwise browsers keep the previous release's UI)."""

import pytest
from fastapi import HTTPException

import app.main as main


@pytest.fixture
def gravityui(monkeypatch, tmp_path):
    build = tmp_path / "static-vue"
    build.mkdir()
    (build / "index.html").write_text("<!doctype html><title>GravityUI</title>")
    monkeypatch.setattr(main, "_resolve_frontend_vue_dir", lambda: build)
    return build


async def test_gravityui_index_is_served_with_no_cache(gravityui, client):
    response = await client.get("/frontend-vue/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "GravityUI" in response.text


@pytest.mark.parametrize("url", ["/", "/?ui=react", "/?ui=vue"])
async def test_root_always_opens_gravityui(gravityui, client, url):
    """The switch links of the former classic view no longer pick another interface."""
    response = await client.get(url, cookies={"gl_ui": "react"}, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/frontend-vue/"
    assert "set-cookie" not in response.headers


async def test_root_reports_status_without_a_build(monkeypatch, tmp_path, client):
    monkeypatch.setattr(main, "_resolve_frontend_vue_dir", lambda: tmp_path / "missing")
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "online"


# --- old addresses of the classic view --------------------------------------------------------

@pytest.mark.parametrize("path", ["devices", "settings/network", "assets/index-abc123.js", "static/index.html"])
async def test_old_addresses_redirect_to_gravityui(path):
    response = await main.redirect_to_gravityui(path)
    assert response.status_code == 307
    assert response.headers["location"] == "/frontend-vue/"


async def test_unknown_api_paths_stay_not_found():
    with pytest.raises(HTTPException) as exc:
        await main.redirect_to_gravityui("api/nothing-here")
    assert exc.value.status_code == 404


@pytest.mark.parametrize("path", ["../etc/passwd", "/etc/passwd", "a\\b"])
async def test_redirect_rejects_traversal(path):
    with pytest.raises(HTTPException) as exc:
        await main.redirect_to_gravityui(path)
    assert exc.value.status_code == 400


# --- the default-interface setting is gone --------------------------------------------------

async def test_retired_default_frontend_key_is_dropped_not_refused(client, admin_token):
    """A GravityUI tab from before the update still sends the key with its form: the save must work."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = await client.post("/api/settings", json={"ui.default_frontend": "react", "dns.server": "192.0.2.53"}, headers=headers)
    assert res.status_code == 200, res.text
    stored = (await client.get("/api/settings", headers=headers)).json()
    assert stored["dns.server"] == "192.0.2.53"
    assert "ui.default_frontend" not in stored


async def test_old_bookmarks_redirect_through_the_app(gravityui, monkeypatch, client):
    """The catch-all is registered at import only when a build exists, so add it to a fresh app here."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()
    app.get("/{full_path:path}")(main.redirect_to_gravityui)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        page = await c.get("/devices", follow_redirects=False)
        api = await c.get("/api/nothing", follow_redirects=False)
    assert (page.status_code, page.headers["location"]) == (307, "/frontend-vue/")
    assert api.status_code == 404
