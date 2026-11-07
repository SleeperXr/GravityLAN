"""Health overview and device detail: what each device entry, agent block, incident and KPI carries.

Written before get_health_overview and get_device_health_detail were split into helpers, so the
split can be checked field by field.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.agent import AgentToken, DeviceMetrics
from app.models.device import Device, DeviceGroup, DeviceHealthSample, DeviceHistory, Service


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
async def scenario(db):
    now = datetime.now(UTC)
    group = DeviceGroup(name="Server", icon="server", sort_order=1)
    db.add(group)
    await db.flush()

    a = Device(ip="192.0.2.10", display_name="Server-A", device_type="server", is_online=True, has_agent=True, group_id=group.id)
    b = Device(ip="192.0.2.20", hostname="printer.lan", device_type="unknown", is_online=False, alert_offline=False)
    c = Device(ip="192.0.2.30", device_type="unknown", is_online=True)
    hidden = Device(ip="192.0.2.40", display_name="Hidden", device_type="unknown", is_online=False, is_hidden=True)
    e = Device(ip="192.0.2.50", display_name="Busy", device_type="server", is_online=True)
    db.add_all([a, b, c, hidden, e])
    await db.flush()

    db.add_all([
        Service(device_id=a.id, name="Web", protocol="https", port=443, is_up=True, latency_ms=3.5, ssl_expiry_days=10),
        Service(device_id=a.id, name="SSH", protocol="ssh", port=22, is_up=False),
        AgentToken(device_id=a.id, token="tok-a", agent_version="1.2.3", last_seen=_naive(now - timedelta(seconds=30))),
        AgentToken(device_id=c.id, token="tok-c", last_seen=_naive(now - timedelta(hours=1))),
        DeviceMetrics(device_id=a.id, cpu_percent=10.0, ram_percent=20.0, timestamp=_naive(now - timedelta(minutes=5))),
        DeviceMetrics(
            device_id=a.id, cpu_percent=95.0, ram_percent=40.0, temperature=80.0, patch_available=5,
            patch_security=2, reboot_required=True, major_upgrade_available="24.04", timestamp=_naive(now - timedelta(minutes=1)),
        ),
    ])
    for i in range(3):
        db.add(DeviceHealthSample(device_id=a.id, timestamp=_naive(now - timedelta(minutes=10 * (i + 1))),
                                  is_online=True, latency_ms=2.0 + i, probe_type="icmp", ports_up=1, ports_total=2))
    for i in range(300):
        db.add(DeviceHealthSample(device_id=e.id, timestamp=_naive(now - timedelta(hours=23) + timedelta(minutes=4 * i)),
                                  is_online=True, latency_ms=1.0 + (i % 7), probe_type="tcp", ports_up=1, ports_total=1))
    db.add_all([
        DeviceHistory(device_id=b.id, status="offline", message="b offline", timestamp=_naive(now - timedelta(hours=1))),
        DeviceHistory(device_id=b.id, status="online", message="b online", timestamp=_naive(now - timedelta(hours=2))),
        DeviceHistory(device_id=c.id, status="down", message="c down", timestamp=_naive(now - timedelta(hours=3))),
        DeviceHistory(device_id=c.id, status="flapping", message="c flaps", timestamp=_naive(now - timedelta(hours=4))),
        DeviceHistory(device_id=c.id, status="offline", message="c offline", timestamp=_naive(now - timedelta(hours=5))),
        DeviceHistory(device_id=hidden.id, status="offline", message="hidden", timestamp=_naive(now - timedelta(hours=1))),
    ])
    await db.commit()
    return {"a": a.id, "b": b.id, "c": c.id, "e": e.id}


AGENT_A = {
    "has_agent": True, "agent_version": "1.2.3", "is_active": True, "cpu_percent": 95.0, "ram_percent": 40.0,
    "temperature": 80.0, "patch_available": 5, "patch_security": 2, "reboot_required": True,
    "major_upgrade_available": "24.04",
}
AGENT_C = {
    "has_agent": True, "agent_version": None, "is_active": False, "cpu_percent": None, "ram_percent": None,
    "temperature": None, "patch_available": 0, "patch_security": 0, "reboot_required": False,
    "major_upgrade_available": None,
}


@pytest.mark.asyncio
async def test_overview_device_entries_kpis_and_incidents(client, auth, scenario):
    data = (await client.get("/api/health/overview?period=24h", headers=auth)).json()
    devices = {d["ip"]: d for d in data["devices"]}

    assert set(devices) == {"192.0.2.10", "192.0.2.20", "192.0.2.30", "192.0.2.50"}  # the hidden one is left out
    a, b, c = devices["192.0.2.10"], devices["192.0.2.20"], devices["192.0.2.30"]

    assert (a["display_name"], a["group_name"], a["agent"]) == ("Server-A", "Server", AGENT_A)
    assert [(s["name"], s["is_up"], s["ssl_expiry_days"], s["ignore_ssl"], s["latency_ms"]) for s in a["services"]] == [
        ("Web", True, 10, False, 3.5), ("SSH", False, None, False, None),
    ]
    # 100 - 20 (SSH down) - 5 (certificate) - 15 (patches, reboot) - 10 (CPU) - 10 (temperature)
    assert (a["health_score"], a["health_status"]) == (40, "critical")
    assert (b["display_name"], b["agent"], b["health_status"], b["alert_offline"]) == ("printer.lan", None, "standby", False)
    assert (c["display_name"], c["agent"], c["group_name"]) == ("192.0.2.30", AGENT_C, None)
    # its agent went silent and nothing else answers
    assert (c["health_score"], c["health_status"]) == (0, "offline")

    kpis = data["kpis"]
    assert {k: kpis[k] for k in (
        "network_health_score", "total_devices", "online_devices", "offline_devices", "flapping_devices",
        "active_issues_count", "ssl_warning_count", "patch_warning_count",
    )} == {
        "network_health_score": 60, "total_devices": 4, "online_devices": 2, "offline_devices": 1,
        "flapping_devices": 0, "active_issues_count": 2, "ssl_warning_count": 1, "patch_warning_count": 1,
    }
    assert kpis["avg_latency_ms"] is not None

    incidents = [(i["message"], i["severity"], i["device_name"]) for i in data["recent_incidents"]]
    assert incidents == [
        ("b online", "info", "printer.lan"),        # b may sleep: its offline entry is left out
        ("c down", "critical", "192.0.2.30"),
        ("c flaps", "warn", "192.0.2.30"),
        ("c offline", "critical", "192.0.2.30"),
    ]


@pytest.mark.asyncio
async def test_detail_device_agent_incidents_and_downsampled_series(client, auth, scenario):
    a = (await client.get(f"/api/health/device/{scenario['a']}?period=24h", headers=auth)).json()
    assert a["device"]["agent"] == AGENT_A
    assert [p["latency_ms"] for p in a["time_series"]] == [4.0, 3.0, 2.0]
    assert a["time_series"][0]["ports_up"] == 1 and a["time_series"][0]["ports_total"] == 2

    c = (await client.get(f"/api/health/device/{scenario['c']}?period=24h", headers=auth)).json()
    assert c["device"]["agent"] == AGENT_C
    # The detail view counts a plain "down" entry as info, unlike the overview
    assert [(i["message"], i["severity"]) for i in c["incidents"]] == [
        ("c down", "info"), ("c flaps", "warn"), ("c offline", "critical"),
    ]

    b = (await client.get(f"/api/health/device/{scenario['b']}?period=24h", headers=auth)).json()
    assert [i["message"] for i in b["incidents"]] == ["b online"]
    assert b["device"]["agent"] is None

    e = (await client.get(f"/api/health/device/{scenario['e']}?period=24h", headers=auth)).json()
    series = e["time_series"]
    assert len(series) == 120
    assert (series[0]["latency_ms"], series[-1]["latency_ms"]) == (1.0, 1.0 + (299 % 7))
    assert series[1]["latency_ms"] == 1.0 + (2 % 7)  # every 2.5th sample: 300 / 120


@pytest.mark.asyncio
async def test_detail_unknown_device_is_404(client, auth):
    assert (await client.get("/api/health/device/9999", headers=auth)).status_code == 404
