"""Tests for the setup wizard API (app/api/setup.py): host adoption, re-runs of stored values and failure paths."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import ipaddress
import pytest
from sqlalchemy import select

from app.api import setup
from app.models.device import Device, DiscoveredHost, Service
from app.models.setting import Setting
from app.schemas.scan import SubnetInfo
from app.services.auth_service import verify_password

LOCAL = [SubnetInfo(interface_name="eth0", ip_address="192.168.100.20", subnet="192.168.100.0/24", netmask="255.255.255.0")]
NETS = [ipaddress.ip_network("192.168.100.0/24")]
GROUPS = {"Server": 1, "NAS / Storage": 2, "Newly discovered": 99}

NAS = {
    "device_type": "nas",
    "device_subtype": "Synology",
    "services": [
        {"name": "DSM (HTTPS)", "protocol": "https", "port": 5001, "url_template": "https://{ip}:5001", "color": "#00f"},
        {"name": "Bad", "protocol": "http", "port": 81, "url_template": "javascript:alert(1)"},
    ],
}


def _host(ip="192.168.100.30", hostname="nas.lan", mac="aa:bb:cc:dd:ee:01", custom_name=None):
    return SimpleNamespace(ip=ip, hostname=hostname, mac=mac, vendor="Synology", custom_name=custom_name)


@pytest.fixture
def scan(monkeypatch):
    """Port scan, name lookup and classifier doubles; the classifier answers NAS unless told otherwise."""
    fakes = SimpleNamespace(
        ports=AsyncMock(return_value=[5001]),
        resolve=AsyncMock(return_value=None),
        classify=lambda info: NAS,
    )
    monkeypatch.setattr("app.scanner.port_scanner.scan_ports", fakes.ports)
    monkeypatch.setattr("app.scanner.hostname.resolve_hostname", fakes.resolve)
    monkeypatch.setattr("app.scanner.classifier.classify_device", lambda info: fakes.classify(info))
    return fakes


# --- helpers ----------------------------------------------------------------

def test_subnets_are_normalized_and_none_stays_none():
    assert setup.SetupCompleteRequest(subnets=[" 10.0.0.5/24 "]).subnets == ["10.0.0.0/24"]
    assert setup.SetupCompleteRequest().subnets is None
    assert setup.SetupCompleteRequest(subnets=None).subnets is None  # an explicit null from the wizard


def test_adoption_networks_prefer_the_scanned_subnets():
    assert setup._adoption_networks(["10.0.0.0/24"], LOCAL) == [ipaddress.ip_network("10.0.0.0/24")]
    assert setup._adoption_networks(None, LOCAL) == NETS


def test_in_adoption_networks():
    assert setup._in_adoption_networks(_host(ip="192.168.100.7"), NETS) is True
    assert setup._in_adoption_networks(_host(ip="10.0.0.7"), NETS) is False
    assert setup._in_adoption_networks(_host(ip="not-an-ip"), NETS) is False


# --- _process_discovered_host ---------------------------------------------------

@pytest.mark.asyncio
async def test_host_outside_the_networks_or_already_known_is_skipped_without_a_scan(scan):
    assert await setup._process_discovered_host(_host(ip="10.0.0.7"), GROUPS, set(), NETS, None) is None
    assert await setup._process_discovered_host(_host(), GROUPS, {"192.168.100.30"}, NETS, None) is None
    scan.ports.assert_not_awaited()


@pytest.mark.asyncio
async def test_host_becomes_a_device_with_safe_services_in_its_group(scan):
    device, services, host = await setup._process_discovered_host(_host(), GROUPS, set(), NETS, None)

    assert (device.display_name, device.device_type, device.device_subtype, device.group_id) == ("nas", "nas", "Synology", 2)
    assert [(s.name, s.port, s.url_template) for s in services] == [
        ("DSM (HTTPS)", 5001, "https://{ip}:5001"),
        ("Bad", 81, ""),  # an unsafe link template is dropped, the service stays
    ]
    scan.resolve.assert_not_awaited()  # a real name needs no second lookup


@pytest.mark.asyncio
async def test_ip_like_name_is_looked_up_again_with_the_dns_server(scan):
    scan.resolve.return_value = "fileserver.home.arpa"
    host = _host(hostname="192.168.100.30")

    device, _, _ = await setup._process_discovered_host(host, GROUPS, set(), NETS, "192.168.100.2")

    assert scan.resolve.await_args.kwargs["dns_server"] == "192.168.100.2"
    assert device.hostname == "fileserver.home.arpa"
    assert device.display_name == "fileserver"
    assert host.hostname == "fileserver.home.arpa"


@pytest.mark.asyncio
async def test_without_a_name_the_custom_name_or_the_ip_is_shown(scan):
    device, _, _ = await setup._process_discovered_host(_host(hostname=None, custom_name="Keller-NAS"), GROUPS, set(), NETS, None)
    assert device.display_name == "Keller-NAS"

    device, _, _ = await setup._process_discovered_host(_host(hostname=None), GROUPS, set(), NETS, None)
    assert device.display_name == "192.168.100.30"


@pytest.mark.asyncio
async def test_unknown_type_goes_to_newly_discovered(scan):
    scan.classify = lambda info: {"device_type": "printer", "services": NAS["services"][:1]}
    device, _, _ = await setup._process_discovered_host(_host(), GROUPS, set(), NETS, None)
    assert device.group_id == 99
    assert device.device_subtype == "Unknown"


@pytest.mark.asyncio
async def test_host_without_services_is_not_adopted(scan):
    scan.classify = lambda info: None
    assert await setup._process_discovered_host(_host(), GROUPS, set(), NETS, None) is None


# --- /api/setup/complete ----------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_adopts_online_hosts_and_marks_the_first_scan_done(monkeypatch, client, db, scan):
    monkeypatch.setattr("app.scanner.utils.get_local_subnets", lambda: LOCAL)
    db.add_all([
        DiscoveredHost(ip="192.168.100.30", hostname="nas.lan", mac="aa:bb:cc:dd:ee:01", is_online=True),
        DiscoveredHost(ip="192.168.100.31", hostname="old.lan", is_online=False),
        DiscoveredHost(ip="10.9.9.9", hostname="far.lan", is_online=True),
    ])
    await db.commit()

    res = await client.post("/api/setup/complete", json={"admin_password": "supersecretpassword123"})

    assert res.status_code == 200
    assert res.json()["devices_adopted"] == 1
    device = (await db.execute(select(Device))).scalar_one()
    assert device.ip == "192.168.100.30"
    services = (await db.execute(select(Service).where(Service.device_id == device.id))).scalars().all()
    assert len(services) == 2
    adopted = (await db.execute(select(DiscoveredHost).where(DiscoveredHost.ip == "192.168.100.30"))).scalar_one()
    await db.refresh(adopted)
    assert adopted.is_monitored is True
    initial = (await db.execute(select(Setting).where(Setting.key == "scanner.initial_scan_done"))).scalar_one()
    assert initial.value == "true"


@pytest.mark.asyncio
async def test_complete_overwrites_stored_dns_and_password_and_an_unfinished_flag(monkeypatch, client, db):
    monkeypatch.setattr("app.scanner.utils.get_local_subnets", lambda: LOCAL)
    db.add_all([
        Setting(key="setup.complete", value="false"),
        Setting(key="dns.server", value="1.1.1.1"),
        Setting(key="api.admin_password", value="old-hash"),
        Setting(key="api.master_token", value="existing-master-token"),
    ])
    await db.commit()

    res = await client.post(
        "/api/setup/complete", json={"admin_password": "supersecretpassword123", "dns_server": "192.168.100.2"}
    )

    assert res.status_code == 200
    assert res.json()["devices_adopted"] == 0
    values = {s.key: s.value for s in (await db.execute(select(Setting))).scalars().all()}
    assert values["setup.complete"] == "true"
    assert values["dns.server"] == "192.168.100.2"
    assert values["api.master_token"] == "existing-master-token"
    assert verify_password("supersecretpassword123", values["api.admin_password"])
    rows = (await db.execute(select(Setting).where(Setting.key.in_(["setup.complete", "dns.server"])))).scalars().all()
    assert len(rows) == 2  # updated in place, no second row

    # Calling complete again when already completed is rejected with 400
    again = await client.post("/api/setup/complete", json={"admin_password": "otherpassword123"})
    assert again.status_code == 400


@pytest.mark.asyncio
async def test_failing_subnet_registration_and_adoption_still_complete_the_setup(monkeypatch, client, db):
    monkeypatch.setattr("app.scanner.utils.get_local_subnets", lambda: LOCAL)
    monkeypatch.setattr(setup, "_register_scan_subnets", AsyncMock(side_effect=RuntimeError("subnet table locked")))
    monkeypatch.setattr(setup, "_adopt_discovered_hosts", AsyncMock(side_effect=RuntimeError("scan failed")))

    res = await client.post("/api/setup/complete", json={"admin_password": "supersecretpassword123"})

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "devices_adopted": 0}
    assert res.headers.get("set-cookie")  # the admin is still signed in
    done = (await db.execute(select(Setting).where(Setting.key == "setup.complete"))).scalar_one()
    assert done.value == "true"
