"""POST /api/settings pinned before the update_settings refactor: refusals, URL mirroring, legacy scan_subnets,
validators, insert vs. update, the log level and when the step-up grant duration asks for a password."""

import pytest
from sqlalchemy import select

import app.api.settings as settings_api
from app.models.network import Subnet
from app.models.setting import Setting


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


async def _values(db):
    db.expire_all()
    return {s.key: s.value for s in (await db.execute(select(Setting))).scalars().all()}


@pytest.mark.asyncio
async def test_protected_and_unknown_keys_are_refused_with_their_names(client, auth):
    res = await client.post("/api/settings", json={"api.admin_password": "x", "api.master_token": "y"}, headers=auth)
    assert res.status_code == 400
    assert res.json()["detail"].startswith("api.admin_password, api.master_token cannot be changed here")

    res = await client.post("/api/settings", json={"zzz.unknown": "1", "aaa.unknown": "2"}, headers=auth)
    assert res.status_code == 400
    assert res.json()["detail"] == "aaa.unknown, zzz.unknown cannot be changed through /api/settings."


@pytest.mark.asyncio
@pytest.mark.parametrize(("sent", "stored"), [
    ({"server_url_override": "http://a:8000"}, {"server_url_override": "http://a:8000", "server.url": "http://a:8000"}),
    ({"server.url": "http://b:8000"}, {"server_url_override": "http://b:8000", "server.url": "http://b:8000"}),
    ({"server.url": "http://c", "server_url_override": "http://d"}, {"server.url": "http://c", "server_url_override": "http://d"}),
])
async def test_server_url_is_mirrored_when_only_one_name_is_sent(client, db, auth, sent, stored):
    assert (await client.post("/api/settings", json=sent, headers=auth)).status_code == 200
    values = await _values(db)
    assert {k: values[k] for k in stored} == stored


@pytest.mark.asyncio
async def test_existing_settings_are_updated_and_new_ones_added(client, db, auth):
    db.add(Setting(key="dns.server", value="1.1.1.1"))
    await db.commit()
    res = await client.post("/api/settings", json={"dns.server": "192.168.1.2", "ui.default_frontend": "vue"}, headers=auth)
    assert res.status_code == 200, res.text
    values = await _values(db)
    assert (values["dns.server"], values["ui.default_frontend"]) == ("192.168.1.2", "vue")
    rows = (await db.execute(select(Setting).where(Setting.key == "dns.server"))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_legacy_scan_subnets_go_to_the_subnet_table(client, db, auth):
    res = await client.post("/api/settings", json={"scan_subnets": "192.168.50.0/24, ,10.9.0.0/24"}, headers=auth)
    assert res.status_code == 200, res.text
    assert "scan_subnets" not in await _values(db)
    cidrs = {s.cidr for s in (await db.execute(select(Subnet))).scalars().all()}
    assert {"192.168.50.0/24", "10.9.0.0/24"} <= cidrs


@pytest.mark.asyncio
async def test_validators_run_only_for_values_that_are_set(client, db, auth, monkeypatch):
    seen = []
    monkeypatch.setitem(settings_api._VALIDATORS, "dns.server", lambda v: seen.append(v))
    await client.post("/api/settings", json={"dns.server": ""}, headers=auth)
    await client.post("/api/settings", json={"dns.server": "9.9.9.9"}, headers=auth)
    assert seen == ["9.9.9.9"]


@pytest.mark.asyncio
async def test_log_level_is_applied_after_saving(client, auth, monkeypatch):
    applied = []
    monkeypatch.setattr("app.services.log_streamer.apply_log_level", applied.append)
    assert (await client.post("/api/settings", json={"system.log_level": "DEBUG"}, headers=auth)).status_code == 200
    assert applied == ["DEBUG"]


@pytest.mark.asyncio
async def test_grant_duration_asks_for_the_password_only_when_it_changes(client, db, auth, monkeypatch):
    from app.services import stepup

    checks = []
    monkeypatch.setattr(stepup, "check", lambda request, area: checks.append(area))

    unchanged = str(stepup.DEFAULT_MINUTES)
    assert (await client.post("/api/settings", json={stepup.SETTING_KEY: unchanged}, headers=auth)).status_code == 200
    assert checks == []

    assert (await client.post("/api/settings", json={stepup.SETTING_KEY: "20"}, headers=auth)).status_code == 200
    assert checks == ["instance"]

    assert (await client.post("/api/settings", json={stepup.SETTING_KEY: "20"}, headers=auth)).status_code == 200
    assert checks == ["instance"]  # now stored, so no new question
