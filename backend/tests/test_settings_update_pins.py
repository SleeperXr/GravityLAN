"""POST /api/settings pinned before the update_settings refactor: refusals, URL mirroring, legacy scan_subnets,
validators, insert vs. update, the log level and when the step-up grant duration asks for a password."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import app.api.settings as settings_api
from app.models.device import Device
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
async def test_get_all_settings_mirrors_both_directions(client, db, auth):
    db.add(Setting(key="server.url", value="http://only-server:8000"))
    await db.commit()
    res = await client.get("/api/settings", headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert data["server.url"] == "http://only-server:8000"
    assert data["server_url_override"] == "http://only-server:8000"

    await db.execute(Setting.__table__.delete().where(Setting.key.in_(("server.url", "server_url_override"))))
    db.add(Setting(key="server_url_override", value="http://only-override:8000"))
    await db.commit()
    res2 = await client.get("/api/settings", headers=auth)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["server_url_override"] == "http://only-override:8000"
    assert data2["server.url"] == "http://only-override:8000"


@pytest.mark.asyncio
async def test_existing_settings_are_updated_and_new_ones_added(client, db, auth):
    db.add(Setting(key="dns.server", value="1.1.1.1"))
    await db.commit()
    res = await client.post("/api/settings", json={"dns.server": "192.168.1.2", "ui.start_page": "/health"}, headers=auth)
    assert res.status_code == 200, res.text
    values = await _values(db)
    assert (values["dns.server"], values["ui.start_page"]) == ("192.168.1.2", "/health")
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
async def test_store_setting_helper_persists_single_key(db):
    await settings_api._store_setting(db, "dns.server", "8.8.4.4")
    await db.commit()
    values = await _values(db)
    assert values["dns.server"] == "8.8.4.4"


@pytest.mark.asyncio
async def test_clearing_secondary_dns_resets_device_dns_names(client, db, auth):
    dev = Device(ip="192.168.1.55", display_name="host", dns_names='{"2": "host.local"}', hostname_source="dns2")
    db.add(dev)
    await db.commit()

    res = await client.post("/api/settings", json={"dns.server_secondary": ""}, headers=auth)
    assert res.status_code == 200
    await db.refresh(dev)
    assert dev.dns_names is None
    assert dev.hostname_source is None


@pytest.mark.asyncio
async def test_health_resilience_and_orbit_visibility_validators(client, auth):
    assert (await client.post("/api/settings", json={"ui.health_resilience": "auto"}, headers=auth)).status_code == 200
    assert (await client.post("/api/settings", json={"ui.health_resilience": "invalid"}, headers=auth)).status_code == 400

    assert (await client.post("/api/settings", json={"ui.orbit_visibility": '{"1": true, "2": false}'}, headers=auth)).status_code == 200
    assert (await client.post("/api/settings", json={"ui.orbit_visibility": "not-json"}, headers=auth)).status_code == 400
    assert (await client.post("/api/settings", json={"ui.orbit_visibility": '{"abc": true}'}, headers=auth)).status_code == 400


def test_check_server_url_rejects_unapproved_path_characters():
    with pytest.raises(ValueError, match="path contains unsupported characters"):
        settings_api.check_server_url("http://192.168.1.1:8000/bad,path")


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


@pytest.mark.asyncio
async def test_reset_database_handles_scheduler_and_table_errors(db, monkeypatch, tmp_path):
    from app.config import settings as app_config
    from app.scanner.scheduler import scheduler

    async def fail_stop():
        raise TimeoutError("stop timed out")

    async def fail_start():
        raise RuntimeError("start failed")

    monkeypatch.setattr(scheduler, "stop", fail_stop)
    monkeypatch.setattr(scheduler, "start", fail_start)
    monkeypatch.setattr(app_config, "data_dir", tmp_path)
    cleanup_copy = tmp_path / "gravitylan.pre-cleanup-20260101.db"
    cleanup_copy.write_text("dummy")

    orig_run_sync = db.run_sync

    async def run_sync_with_missing_table(fn, *args, **kwargs):
        def wrapper(sync_conn):
            real_execute = sync_conn.execute

            def flaky_execute(stmt, *a, **kw):
                if "api_tokens" in str(stmt):
                    raise OperationalError("DELETE FROM api_tokens", {}, Exception("no such table"))
                return real_execute(stmt, *a, **kw)

            sync_conn.execute = flaky_execute
            try:
                return fn(sync_conn, *args, **kwargs)
            finally:
                sync_conn.execute = real_execute

        return await orig_run_sync(wrapper)

    monkeypatch.setattr(db, "run_sync", run_sync_with_missing_table)
    res = await settings_api.reset_database(request=None, db=db)
    assert res["status"] == "success"
    assert not cleanup_copy.exists()


@pytest.mark.asyncio
async def test_reset_database_rolls_back_and_raises_500_on_fatal_error(db, monkeypatch):
    from app.scanner.scheduler import scheduler

    async def noop():
        return None

    async def boom(_fn):
        raise RuntimeError("disk I/O failure")

    monkeypatch.setattr(scheduler, "stop", noop)
    monkeypatch.setattr(db, "run_sync", boom)

    with pytest.raises(HTTPException) as exc_info:
        await settings_api.reset_database(request=None, db=db)
    assert exc_info.value.status_code == 500
    assert "disk I/O failure" in exc_info.value.detail
