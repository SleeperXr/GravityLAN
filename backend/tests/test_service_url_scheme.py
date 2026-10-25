"""Service links only use allow-listed schemes (#42, GHSA-f8v7-pmx7-g85w)."""
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.api import backup
from app.database.migrations import _clear_unsafe_service_links
from app.models.device import Device, Service
from app.schemas.device import ServiceCreate, ServiceUpdate, is_safe_url_template

from tests.test_backup_import import _query, backup_db  # noqa: F401  (fixture)

UNSAFE = [
    "javascript:alert(document.domain)",
    " JavaScript:alert(1)",
    "java\tscript:alert(1)",
    "\x01javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "{ip}:{port}",
]
SAFE = ["", "http://{ip}:{port}", "https://{ip}:8006", "ssh://{ip}", "smb://{ip}", "rdp://{ip}", "vnc://{ip}:5900", "scp://{ip}"]


@pytest.mark.parametrize("value", UNSAFE)
def test_unsafe_templates_rejected(value):
    assert not is_safe_url_template(value)
    with pytest.raises(ValidationError):
        ServiceCreate(name="x", port=80, url_template=value)
    with pytest.raises(ValidationError):
        ServiceUpdate(url_template=value)


@pytest.mark.parametrize("value", SAFE)
def test_safe_templates_accepted(value):
    assert is_safe_url_template(value)
    assert ServiceCreate(name="x", port=80, url_template=value).url_template == value


@pytest.mark.asyncio
async def test_api_rejects_javascript_link(client, db, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    db.add(Device(id=7, ip="192.168.1.7", display_name="nas"))
    await db.commit()

    bad = await client.post(
        "/api/devices/7/services",
        json={"name": "evil", "port": 80, "url_template": "javascript:alert(1)"},
        headers=headers,
    )
    assert bad.status_code == 422

    good = await client.post(
        "/api/devices/7/services", json={"name": "web", "port": 8080, "url_template": "http://{ip}:{port}"}, headers=headers
    )
    assert good.status_code == 200
    assert good.json()["url_template"] == "http://{ip}:{port}"

    patch = await client.patch(
        f"/api/services/{good.json()['id']}", json={"url_template": "data:text/html,x"}, headers=headers
    )
    assert patch.status_code == 422


def test_backup_import_drops_unsafe_links(backup_db):  # noqa: F811
    backup._write_db(backup_db, {
        "services": [
            {"id": 1, "device_id": 1, "name": "evil", "protocol": "http", "port": 80, "url_template": "javascript:alert(1)"},
            {"id": 2, "device_id": 1, "name": "web", "protocol": "https", "port": 443, "url_template": "https://{ip}"},
        ],
    })
    rows = dict(_query(backup_db, "SELECT name, url_template FROM services"))
    assert rows == {"evil": "", "web": "https://{ip}"}


@pytest.mark.asyncio
async def test_migration_clears_stored_unsafe_links(db):
    db.add(Device(id=8, ip="192.168.1.8", display_name="host"))
    db.add(Service(device_id=8, name="evil", protocol="http", port=80, url_template="javascript:alert(1)"))
    db.add(Service(device_id=8, name="ssh", protocol="ssh", port=22, url_template="ssh://{ip}"))
    await db.commit()

    await _clear_unsafe_service_links(db)

    rows = {s.name: s.url_template for s in (await db.execute(select(Service))).scalars()}
    assert rows == {"evil": "", "ssh": "ssh://{ip}"}
