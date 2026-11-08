"""Edges of the agent ARP relay (app/services/agent_scanner_relay.py): MAC validation, probes
without a usable address, malformed entries, updating known discovered hosts, and a broadcast
that fails without losing the ingest."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.services.agent_scanner_relay as relay
from app.models.agent import AgentConfig
from app.models.device import Device, DiscoveredHost
from app.models.network import Subnet


@pytest.mark.parametrize("mac, ok", [
    ("AA:BB:CC:00:00:01", True),
    (None, False),
    ("AA:BB:CC:00:00", False),  # too short
    ("AA-BB-CC-00-00-01", False),  # dashes
    ("00:00:00:00:00:00", False),
    ("ff:ff:ff:ff:ff:ff", False),
    ("GG:BB:CC:00:00:01", False),  # not hex
])
def test_mac_validation(mac, ok):
    assert relay.is_valid_mac_address(mac) is ok


async def _probe(db, ip):
    dev = Device(ip=ip, hostname="probe")
    db.add(dev)
    await db.flush()
    db.add(AgentConfig(device_id=dev.id, enable_scanner_relay=True))
    db.add_all([Subnet(cidr="192.0.2.0/24", name="LAN"), Subnet(cidr="garbage", name="Broken")])
    await db.commit()
    return dev


async def test_a_probe_with_an_unusable_address_relays_nothing(db):
    dev = await _probe(db, "not-an-ip")
    assert await relay.get_probe_networks(db, dev.id) == []


async def test_malformed_subnets_are_skipped(db):
    dev = await _probe(db, "192.0.2.5")
    assert [str(n) for n in await relay.get_probe_networks(db, dev.id)] == ["192.0.2.0/24"]


async def test_entries_without_ip_or_mac_or_with_bad_values_are_skipped(db):
    dev = await _probe(db, "192.0.2.5")
    entries = [
        {"ip": "192.0.2.10"},  # no MAC
        {"ip": "nonsense", "mac": "aa:bb:cc:00:00:10"},
        {"ip": "192.0.2.11", "mac": "00:00:00:00:00:00"},
        SimpleNamespace(ip="192.0.2.12", mac="aa:bb:cc:00:00:12"),  # objects work like dicts
    ]
    assert await relay.ingest_agent_arp_table(db, dev.id, entries) == 1
    hosts = (await db.execute(select(DiscoveredHost))).scalars().all()
    assert [(h.ip, h.mac) for h in hosts] == [("192.0.2.12", "AA:BB:CC:00:00:12")]


async def test_a_known_discovered_host_is_refreshed(db, monkeypatch):
    dev = await _probe(db, "192.0.2.5")
    db.add(DiscoveredHost(ip="192.0.2.20", mac="AA:BB:CC:00:00:99", vendor=None, is_online=False))
    await db.commit()
    monkeypatch.setattr(relay, "get_vendor", lambda mac: "Vendor")

    assert await relay.ingest_agent_arp_table(db, dev.id, [{"ip": "192.0.2.20", "mac": "aa:bb:cc:00:00:20"}]) == 1
    host = (await db.execute(select(DiscoveredHost))).scalar_one()
    assert (host.mac, host.vendor, host.is_online) == ("AA:BB:CC:00:00:20", "Vendor", True)


async def test_an_unchanged_device_counts_nothing(db):
    dev = await _probe(db, "192.0.2.5")
    db.add(Device(ip="192.0.2.30", mac="AA:BB:CC:00:00:30", vendor="Known", is_online=True))
    await db.commit()
    assert await relay.ingest_agent_arp_table(db, dev.id, [{"ip": "192.0.2.30", "mac": "aa:bb:cc:00:00:30"}]) == 0


async def test_a_failing_broadcast_keeps_the_ingest(db, monkeypatch):
    dev = await _probe(db, "192.0.2.5")

    async def broken(progress):
        raise RuntimeError("no listeners")

    monkeypatch.setattr("app.api.scanner.state.broadcast", broken)
    assert await relay.ingest_agent_arp_table(db, dev.id, [{"ip": "192.0.2.40", "mac": "aa:bb:cc:00:00:40"}]) == 1
    assert (await db.execute(select(DiscoveredHost.ip))).scalars().all() == ["192.0.2.40"]
