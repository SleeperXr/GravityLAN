"""POST /api/settings only writes allow-listed keys (#41, GHSA-cwcv-4vrx-xpxv)."""
import pytest
from sqlalchemy import select

from app.models.setting import Setting


async def _settings_write_token(client, admin_token: str) -> str:
    res = await client.post(
        "/api/auth/tokens",
        json={"name": "automation", "scopes": ["settings:read", "settings:write"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    return res.json()["token"]


@pytest.mark.asyncio
async def test_settings_write_token_cannot_reopen_setup(client, db, admin_token):
    token = await _settings_write_token(client, admin_token)

    res = await client.post(
        "/api/settings", json={"setup.complete": "false"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 400
    assert "setup.complete" in res.json()["detail"]

    setup = (await db.execute(select(Setting).where(Setting.key == "setup.complete"))).scalar_one()
    await db.refresh(setup)
    assert setup.value == "true"

    # The unauthenticated wizard endpoint stays closed
    takeover = await client.post("/api/setup/complete", json={"admin_password": "attacker123"})
    assert takeover.status_code == 400
    assert "gravitylan_token" not in takeover.cookies


@pytest.mark.asyncio
async def test_unknown_key_rejected_and_nothing_written(client, db, admin_token):
    res = await client.post(
        "/api/settings",
        json={"scan_interval": "600", "some.unknown_key": "x"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 400
    assert "some.unknown_key" in res.json()["detail"]

    stored = (await db.execute(select(Setting).where(Setting.key == "scan_interval"))).scalar_one_or_none()
    assert stored is None


@pytest.mark.asyncio
async def test_settings_form_keys_still_writable(client, db, admin_token):
    # Exactly what the React and Vue settings pages send, plus the appearance/topology keys
    payload = {
        "scan_interval": "0",
        "quick_scan_interval": "300",
        "scan_timeout": "1.5",
        "scanner.offline_threshold": "3",
        "dns.server": "",
        "history_retention_days": "7",
        "server_url_override": "",
        "system.log_level": "info",
        "ui.start_page": "/",
        "ui.default_frontend": "react",
        "network_groups": "[]",
        "ui.line_colors": "{}",
        "ui.orbit_layout": "custom",
        "ui.orbit_roles": "{}",
        "ui.link_type_colors": "{}",
        "topology.flow_speed": "1.5",
        "topology.sticky_drag": "true",
        "theme.primary_color": "#00ff00",
    }
    res = await client.post("/api/settings", json=payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_get_settings_hides_credentials(client, admin_token):
    res = await client.get("/api/settings", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    assert "api.master_token" not in res.json()
    assert "api.admin_password" not in res.json()


@pytest.mark.asyncio
async def test_health_resilience_card_mode_is_writable_and_checked(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    for mode in ("auto", "on", "off"):
        res = await client.post("/api/settings", json={"ui.health_resilience": mode}, headers=headers)
        assert res.status_code == 200
    stored = await client.get("/api/settings", headers=headers)
    assert stored.json()["ui.health_resilience"] == "off"
    bad = await client.post("/api/settings", json={"ui.health_resilience": "sometimes"}, headers=headers)
    assert bad.status_code == 400
