"""Gateway detection (app/scanner/gateways.py) and the notifications API (app/api/notifications.py):
route-table parsing edges, which gateway a subnet gets and from where, and how history entries
turn into notifications with filters and read state."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import app.scanner.gateways as gw
from app.models.device import Device, DeviceHistory, Service


# --- gateways -------------------------------------------------------------------------------

@pytest.mark.parametrize("cidr, expected", [("192.0.2.0/24", "192.0.2.1"), ("192.0.2.0/31", None), ("garbage", None), (None, None)])
def test_suggest_gateway(cidr, expected):
    assert gw.suggest_gateway(cidr) == expected


def test_hex_to_ipv4_rejects_garbage():
    assert gw._hex_to_ipv4("0102A8C0") == "192.168.2.1"
    assert gw._hex_to_ipv4("zz") is None
    assert gw._hex_to_ipv4("1" * 20) is None


def test_parse_proc_net_route_skips_bad_and_duplicate_lines():
    dump = (
        "Iface\tDestination\tGateway\tFlags\n"
        "eth0\t00000000\t0102A8C0\t0003\n"
        "eth1\t00000000\t0102A8C0\t0003\n"  # same gateway twice
        "eth2\t00000000\t0202A8C0\tXYZ\n"  # unreadable flags
        "eth3\t00000000\t0302A8C0\t0001\n"  # no gateway flag
        "eth4\t0002A8C0\t00000000\t0001\n"  # not a default route
        "short\n"
    )
    assert gw.parse_proc_net_route(dump) == ["192.168.2.1"]


def test_detect_default_gateways(monkeypatch, tmp_path):
    monkeypatch.setattr(gw.sys, "platform", "linux")
    route = tmp_path / "route"
    route.write_text("Iface\tDestination\tGateway\tFlags\neth0\t00000000\t0102A8C0\t0003\n")
    monkeypatch.setattr(gw, "PROC_NET_ROUTE", str(route))
    assert gw.detect_default_gateways() == ["192.168.2.1"]

    monkeypatch.setattr(gw, "PROC_NET_ROUTE", str(tmp_path / "missing"))
    assert gw.detect_default_gateways() == []

    monkeypatch.setattr(gw.sys, "platform", "win32")
    assert gw.detect_default_gateways() == []


def test_detected_in_skips_garbage():
    assert gw._detected_in("garbage", ["192.0.2.1"]) is None
    assert gw._detected_in("192.0.2.0/24", ["not-an-ip", "192.0.2.254"]) == "192.0.2.254"


def test_effective_gateway_order():
    configured = SimpleNamespace(gateway_ip=" 192.0.2.254 ", cidr="192.0.2.0/24")
    assert gw.effective_gateway(configured, []) == gw.EffectiveGateway("192.0.2.254", "configured")
    detected = SimpleNamespace(gateway_ip=None, cidr="192.0.2.0/24")
    assert gw.effective_gateway(detected, ["192.0.2.2"]) == gw.EffectiveGateway("192.0.2.2", "detected")
    suggested = SimpleNamespace(gateway_ip="", cidr="192.0.2.0/24")
    assert gw.effective_gateway(suggested, []) == gw.EffectiveGateway("192.0.2.1", "suggested")
    assert gw.effective_gateway(SimpleNamespace(gateway_ip=None, cidr="192.0.2.7/32"), []) is None


def test_gateway_prefill(monkeypatch):
    assert gw.gateway_prefill("192.0.2.0/24", ["192.0.2.2"]) == gw.EffectiveGateway("192.0.2.2", "detected")
    assert gw.gateway_prefill("192.0.2.0/31", []) is None
    monkeypatch.setattr(gw, "detect_default_gateways", lambda: ["192.0.2.3"])
    assert gw.gateway_prefill("192.0.2.0/24") == gw.EffectiveGateway("192.0.2.3", "detected")


# --- notifications ----------------------------------------------------------------------------

@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
async def history(db):
    nas = Device(ip="192.0.2.20", display_name="NAS")
    cam = Device(ip="192.0.2.30")
    db.add_all([nas, cam])
    await db.flush()
    web = Service(device_id=nas.id, name="Web", protocol="http", port=80)
    db.add(web)
    await db.flush()
    t = datetime(2026, 11, 8, 12, 0)
    db.add_all([
        DeviceHistory(device_id=nas.id, service_id=web.id, status="up", timestamp=t),
        DeviceHistory(device_id=nas.id, service_id=web.id, status="down", timestamp=t + timedelta(minutes=1)),
        DeviceHistory(device_id=nas.id, status="offline", timestamp=t + timedelta(minutes=2), read=True),
        DeviceHistory(device_id=cam.id, status="ip_changed", message="IP changed to 192.0.2.31", timestamp=t + timedelta(minutes=3)),
        DeviceHistory(device_id=cam.id, status="new_device", timestamp=t + timedelta(minutes=4)),
        DeviceHistory(device_id=cam.id, status="rebooted", timestamp=t + timedelta(minutes=5)),
        DeviceHistory(device_id=cam.id, status="online", timestamp=t + timedelta(minutes=6)),
    ])
    await db.commit()
    return SimpleNamespace(nas=nas, cam=cam, start=t)


async def test_every_history_status_becomes_a_typed_notification(client, auth, history):
    items = (await client.get("/api/notifications", headers=auth)).json()
    assert [(i["type"], i["severity"]) for i in items] == [
        ("device_online", "success"), ("unknown", "info"), ("new_device", "info"), ("ip_changed", "info"),
        ("device_offline", "warning"), ("service_down", "error"), ("service_up", "success"),
    ]
    by_type = {i["type"]: i for i in items}
    assert by_type["ip_changed"]["message"] == "IP changed to 192.0.2.31"
    assert by_type["device_offline"]["message"] == "NAS is now offline"
    assert by_type["device_online"]["message"] == "192.0.2.30 is now online"  # no display name: the IP


async def test_filters(client, auth, history):
    unread = (await client.get("/api/notifications?unread=true", headers=auth)).json()
    assert "device_offline" not in [i["type"] for i in unread]
    read = (await client.get("/api/notifications?unread=false", headers=auth)).json()
    assert [i["type"] for i in read] == ["device_offline"]
    cam_only = (await client.get(f"/api/notifications?device_id={history.cam.id}", headers=auth)).json()
    assert {i["device_id"] for i in cam_only} == {history.cam.id}
    since = (history.start + timedelta(minutes=5)).isoformat()
    recent = (await client.get(f"/api/notifications?since={since}", headers=auth)).json()
    assert [i["type"] for i in recent] == ["device_online", "unknown"]
    limited = (await client.get("/api/notifications?limit=2", headers=auth)).json()
    assert len(limited) == 2


async def test_mark_read(client, auth, history):
    first = (await client.get("/api/notifications?unread=true", headers=auth)).json()[0]
    ok = await client.post(f"/api/notifications/{first['id']}/read", headers=auth)
    assert ok.json() == {"status": "success", "id": first["id"], "read": True}
    assert (await client.post("/api/notifications/99999/read", headers=auth)).status_code == 404

    cam = await client.post(f"/api/notifications/read-all?device_id={history.cam.id}", headers=auth)
    assert cam.json()["marked_read"] == 3  # four cam entries, one already read above
    rest = await client.post("/api/notifications/read-all", headers=auth)
    assert rest.json()["marked_read"] == 2  # the two service entries
    assert (await client.get("/api/notifications?unread=true", headers=auth)).json() == []
