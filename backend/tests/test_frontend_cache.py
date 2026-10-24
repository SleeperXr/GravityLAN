"""index.html must not be cached, otherwise browsers keep the previous release's UI."""

import app.main as main


async def test_root_index_is_served_with_no_cache(monkeypatch, tmp_path, client):
    (tmp_path / "index.html").write_text("<!doctype html><title>GravityLAN</title>")
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path)

    async def react_default(db):
        return "react"
    monkeypatch.setattr(main, "_default_frontend", react_default)

    response = await client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "GravityLAN" in response.text


# --- serve_spa path containment ------------------------------------------------

import pytest
from fastapi import HTTPException


@pytest.fixture
def frontend_dir(monkeypatch, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>GravityLAN</title>")
    (static / "app.js").write_text("console.log('ok')")
    monkeypatch.setattr(main, "FRONTEND_DIR", static)
    return static


async def test_serve_spa_serves_files_and_falls_back_to_index(frontend_dir):
    asset = await main.serve_spa("app.js")
    assert asset.path == str(frontend_dir / "app.js")

    route = await main.serve_spa("settings/network")
    assert route.path == str(frontend_dir / "index.html")
    assert route.headers["cache-control"] == "no-cache"


async def test_serve_spa_rejects_sibling_dir_with_same_prefix(frontend_dir):
    """/app/static_other starts with /app/static but is outside it (reached here via a symlink)."""
    sibling = frontend_dir.parent / "static_other"
    sibling.mkdir()
    (sibling / "secret.txt").write_text("token")
    try:
        (frontend_dir / "link").symlink_to(sibling, target_is_directory=True)
    except OSError as e:
        # Windows without admin rights or developer mode (WinError 1314); Linux CI runs it
        pytest.skip(f"cannot create symlinks here: {e}")

    with pytest.raises(HTTPException) as exc:
        await main.serve_spa("link/secret.txt")
    assert exc.value.status_code == 400


@pytest.mark.parametrize("path", ["../etc/passwd", "/etc/passwd", "a\\b"])
async def test_serve_spa_rejects_traversal(frontend_dir, path):
    with pytest.raises(HTTPException) as exc:
        await main.serve_spa(path)
    assert exc.value.status_code == 400


# --- default frontend: `/` opens the chosen interface ---------------------------

@pytest.fixture
def both_frontends(monkeypatch, tmp_path):
    react = tmp_path / "react"
    vue = tmp_path / "vue"
    for d, title in ((react, "React"), (vue, "Vue")):
        d.mkdir()
        (d / "index.html").write_text(f"<!doctype html><title>{title}</title>")
    monkeypatch.setattr(main, "FRONTEND_DIR", react)
    monkeypatch.setattr(main, "_resolve_frontend_vue_dir", lambda: vue)


def _default(monkeypatch, value):
    async def fake(db):
        return value
    monkeypatch.setattr(main, "_default_frontend", fake)


async def test_root_serves_react_by_default(both_frontends, monkeypatch, client):
    _default(monkeypatch, "react")
    response = await client.get("/")
    assert response.status_code == 200
    assert "React" in response.text


async def test_root_redirects_to_gravityui_when_it_is_the_default(both_frontends, monkeypatch, client):
    _default(monkeypatch, "vue")
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/frontend-vue/"


async def test_switch_link_choice_wins_over_the_setting_and_is_remembered(both_frontends, monkeypatch, client):
    _default(monkeypatch, "vue")
    response = await client.get("/?ui=react", follow_redirects=False)
    assert response.status_code == 200
    assert "React" in response.text
    assert "gl_ui=react" in response.headers["set-cookie"]

    remembered = await client.get("/", cookies={"gl_ui": "react"}, follow_redirects=False)
    assert remembered.status_code == 200


async def test_vue_choice_falls_back_to_react_without_a_vue_build(monkeypatch, tmp_path, client):
    (tmp_path / "index.html").write_text("<!doctype html><title>React</title>")
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path)
    monkeypatch.setattr(main, "_resolve_frontend_vue_dir", lambda: tmp_path / "missing")
    response = await client.get("/?ui=vue", follow_redirects=False)
    assert response.status_code == 200
    assert "React" in response.text


async def test_default_frontend_setting_accepts_only_react_or_vue(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    ok = await client.post("/api/settings", json={"ui.default_frontend": "vue"}, headers=headers)
    assert ok.status_code == 200
    stored = await client.get("/api/settings", headers=headers)
    assert stored.json()["ui.default_frontend"] == "vue"

    bad = await client.post("/api/settings", json={"ui.default_frontend": "angular"}, headers=headers)
    assert bad.status_code == 400
    assert "Invalid default frontend" in bad.json()["detail"]


async def test_root_reads_the_default_frontend_setting_from_the_database(both_frontends, client, db):
    from app.models.setting import Setting
    db.add(Setting(key="ui.default_frontend", value="vue"))
    await db.commit()
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/frontend-vue/"
