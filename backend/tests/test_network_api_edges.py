"""Edges of app/api/network.py: cleaning invalid subnets, local subnet parsing, agent probes as
reach for remote subnets, and the update/delete errors (404, 409, 422)."""

import ipaddress
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.api.network as network
from app.models.agent import AgentConfig, AgentToken
from app.models.device import Device
from app.models.network import Subnet


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(autouse=True)
def no_host_lookups(monkeypatch):
    monkeypatch.setattr(network, "detect_default_gateways", lambda: [])
    monkeypatch.setattr("app.scanner.utils.get_local_subnets", lambda: [])


async def test_cleanup_removes_only_invalid_subnets(db, monkeypatch):
    db.add_all([Subnet(cidr="192.0.2.0/24", name="LAN"), Subnet(cidr="garbage", name="Broken")])
    await db.commit()

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(network, "async_session", session)
    await network.cleanup_invalid_subnets()
    assert [s.cidr for s in (await db.execute(select(Subnet))).scalars()] == ["192.0.2.0/24"]


async def test_cleanup_survives_a_database_error(monkeypatch):
    class Broken:
        async def execute(self, _):
            raise RuntimeError("locked")

    @asynccontextmanager
    async def session():
        yield Broken()

    monkeypatch.setattr(network, "async_session", session)
    await network.cleanup_invalid_subnets()  # logged, not raised


def test_parsed_local_subnets_skip_virtual_and_invalid(monkeypatch):
    monkeypatch.setattr("app.scanner.utils.get_local_subnets", lambda: [
        SimpleNamespace(subnet="192.0.2.0/24", interface_name="eth0", is_virtual=False),
        SimpleNamespace(subnet="172.17.0.0/16", interface_name="docker0", is_virtual=True),
        SimpleNamespace(subnet="nonsense", interface_name="weird", is_virtual=False),
    ])
    assert [(str(net), name) for net, name in network._get_parsed_local_subnets()] == [("192.0.2.0/24", "eth0")]


def test_parsed_local_subnets_survive_errors(monkeypatch):
    def broken():
        raise OSError("no interfaces")

    monkeypatch.setattr("app.scanner.utils.get_local_subnets", broken)
    assert network._get_parsed_local_subnets() == []


async def test_agent_probes_name_the_device_and_skip_bad_addresses(db):
    good = Device(ip="198.51.100.7", hostname="probe-host")
    bad = Device(ip="not-an-ip", display_name="Broken")
    db.add_all([good, bad])
    await db.flush()
    for dev, tok in ((good, "a"), (bad, "b")):
        db.add(AgentConfig(device_id=dev.id, enable_scanner_relay=True))
        db.add(AgentToken(device_id=dev.id, token="sha256:" + tok * 64, is_active=True))
    await db.commit()

    probes = await network._get_active_agent_probes(db)
    assert [(str(addr), name, ip) for addr, name, ip in probes] == [("198.51.100.7", "probe-host", "198.51.100.7")]


async def test_agent_probes_survive_a_database_error():
    class Broken:
        async def execute(self, _):
            raise RuntimeError("locked")

    assert await network._get_active_agent_probes(Broken()) == []


def test_enrich_marks_a_remote_subnet_reached_by_an_agent_probe():
    subnet = Subnet(id=1, cidr="198.51.100.0/24", name="IoT", is_enabled=True)
    probes = [(ipaddress.ip_address("198.51.100.7"), "probe-host", "198.51.100.7")]
    res = network._enrich_subnet(subnet, [(ipaddress.ip_network("192.0.2.0/24"), "eth0")], probes)
    assert (res.is_direct_l2, res.is_agent_probe, res.probe_device_name, res.probe_device_ip) == (False, True, "probe-host", "198.51.100.7")


def test_enrich_tolerates_an_invalid_cidr():
    res = network._enrich_subnet(Subnet(id=1, cidr="garbage", name="Broken", is_enabled=True), [], [])
    assert (res.is_direct_l2, res.is_agent_probe) == (False, False)


async def test_update_errors(client, auth, db):
    db.add_all([Subnet(cidr="192.0.2.0/24", name="LAN"), Subnet(cidr="198.51.100.0/24", name="IoT")])
    await db.commit()
    lan, iot = (await db.execute(select(Subnet).order_by(Subnet.id))).scalars().all()

    assert (await client.patch("/api/network/subnets/9999", json={"name": "x"}, headers=auth)).status_code == 404
    taken = await client.patch(f"/api/network/subnets/{iot.id}", json={"cidr": "192.0.2.0/24"}, headers=auth)
    assert taken.status_code == 409
    outside = await client.patch(f"/api/network/subnets/{lan.id}", json={"gateway_ip": "203.0.113.1"}, headers=auth)
    assert outside.status_code == 422


async def test_update_and_delete(client, auth, db):
    db.add(Subnet(cidr="192.0.2.0/24", name="LAN"))
    await db.commit()
    subnet = (await db.execute(select(Subnet))).scalar_one()

    res = await client.patch(f"/api/network/subnets/{subnet.id}", json={"name": "Home", "gateway_ip": "192.0.2.1"}, headers=auth)
    assert (res.status_code, res.json()["name"], res.json()["gateway_ip"]) == (200, "Home", "192.0.2.1")

    assert (await client.delete(f"/api/network/subnets/{subnet.id}", headers=auth)).json() == {"status": "ok"}
    assert (await client.delete(f"/api/network/subnets/{subnet.id}", headers=auth)).status_code == 404
