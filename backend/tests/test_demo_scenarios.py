"""The demo networks in scripts/demo_scenarios.py are hand-written data; catch broken references before the demo seeds them."""

import ipaddress
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from demo_scenarios import SCENARIOS  # noqa: E402

DEFAULT_GROUPS = {"Firewalls", "Server", "NAS / Storage", "Web Interfaces", "Newly discovered"}


@pytest.fixture(params=sorted(SCENARIOS))
def scenario(request):
    return SCENARIOS[request.param]()


def test_names_and_addresses_are_unique(scenario):
    names = [d[0] for d in scenario.devices]
    assert len(names) == len(set(names))
    ips = ([d[1] for d in scenario.devices] + [i[1] for i in scenario.interfaces]
           + [i[0] for i in scenario.router_interfaces] + scenario.pending_router_ips + [h[0] for h in scenario.unknown_hosts])
    assert len(ips) == len(set(ips)), sorted({ip for ip in ips if ips.count(ip) > 1})


def test_every_address_lies_in_a_scenario_subnet(scenario):
    networks = {key: ipaddress.ip_network(cidr) for key, cidr, *_ in scenario.subnets}
    for d in scenario.devices:
        assert any(ipaddress.ip_address(d[1]) in net for net in networks.values()), d[0]
    for name, ip, key, *_ in scenario.interfaces:
        assert ipaddress.ip_address(ip) in networks[key], name
    for ip, key, _vlan in scenario.router_interfaces:
        assert ipaddress.ip_address(ip) in networks[key], ip


def test_references_point_to_known_devices(scenario):
    names = {d[0] for d in scenario.devices}
    groups = DEFAULT_GROUPS | {g[0] for g in scenario.extra_groups}
    seen: set[str] = set()
    for name, _ip, _type, group, flags, _services, _profile in scenario.devices:
        assert group in groups, name
        if flags.get("parent"):
            # The seed resolves parents by name while inserting, so a host must come before its guests
            assert flags["parent"] in seen, name
        seen.add(name)
    for a, b, _kind in scenario.links:
        assert a in names and b in names, (a, b)
    agents = {d[0] for d in scenario.devices if d[6]}
    assert set(scenario.patches) <= agents
    assert scenario.reboot_required <= agents
    assert set(scenario.outages) <= names
    assert {e[0] for e in scenario.down_events} <= names
    assert scenario.router in names
    assert set(scenario.grid) <= names


def test_rack_slots_fit_and_do_not_overlap(scenario):
    units = dict(scenario.racks)
    taken: dict[tuple[str, int], str] = {}
    for name, (rack, top, height) in scenario.rack_slots.items():
        assert rack in units
        assert 1 <= top - height + 1 and top <= units[rack], name
        for u in range(top - height + 1, top + 1):
            assert (rack, u) not in taken, (name, taken.get((rack, u)))
            taken[(rack, u)] = name


def test_company_network_hangs_together():
    scenario = SCENARIOS["company"]()
    adjacency: dict[str, set[str]] = {}
    for a, b, _ in scenario.links:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    reached, queue = {scenario.router}, [scenario.router]
    while queue:
        for nxt in adjacency.get(queue.pop(), ()):
            if nxt not in reached:
                reached.add(nxt)
                queue.append(nxt)
    physical = {d[0] for d in scenario.devices if not d[4].get("virtual_type")}
    assert physical <= reached, sorted(physical - reached)

    aps = {d[0] for d in scenario.devices if d[4].get("is_ap")}
    for name, *_rest in (d for d in scenario.devices if d[4].get("is_wlan")):
        assert adjacency[name] & aps, f"{name} has no access point"
    assert len(scenario.subnets) >= 8 and len(aps) >= 8
