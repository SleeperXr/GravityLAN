"""app/services/interface_service.py: which pairs get suggested, what merging refuses, who answers on a gateway."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

import app.services.interface_service as svc
from app.models.device import Device, DeviceHistory, DeviceInterface, DiscoveredHost
from app.models.network import Subnet
from app.models.setting import Setting
from app.services.interface_service import InterfaceError

MAC = "aa:bb:cc:00:00:01"
LAN_IP, IOT_IP = "192.0.2.10", "198.51.100.10"


@pytest.fixture(autouse=True)
def _no_routes():
    with (
        patch("app.scanner.sync.detect_default_gateways", return_value=[]),
        patch("app.services.interface_service.detect_default_gateways", return_value=[]),
    ):
        yield


async def _vlans(db) -> tuple[Subnet, Subnet]:
    lan = Subnet(cidr="192.0.2.0/24", name="LAN")
    iot = Subnet(cidr="198.51.100.0/24", name="IoT", vlan_id=110)
    db.add_all([lan, iot])
    await db.commit()
    return lan, iot


async def _devices(db, *devices: Device) -> list[Device]:
    db.add_all(devices)
    await db.commit()
    return [await svc.load_device(db, d.id) for d in devices]


def _device(ip: str, name: str = "", mac: str = MAC, **kw) -> Device:
    return Device(ip=ip, mac=mac, display_name=name, is_online=True, **kw)


def _ent(kind="device", id=1, segment="a", gw_source=None) -> dict:
    return {"kind": kind, "id": id, "segment": segment, "gw_source": gw_source}


# --- which pairs are linked --------------------------------------------------

@pytest.mark.parametrize(
    "a, b, reason, linked",
    [
        (_ent(segment="a"), _ent(id=2, segment="b"), "same_mac", True),
        (_ent(segment="a"), _ent(id=2, segment="a"), "same_mac", False),
        (_ent(segment=None), _ent(id=2, segment="b"), "same_mac", False),
        (_ent(segment="a"), _ent(id=2, segment=None), "same_mac", False),
        (_ent("discovered"), _ent("discovered", 2, "b"), "same_mac", False),
        (_ent("discovered"), _ent("device", 2, "b"), "same_mac", True),
        (_ent(gw_source="suggested"), _ent(id=2, segment="b", gw_source="suggested"), "subnet_gateway", False),
        (_ent(gw_source="suggested"), _ent(id=2, segment="b", gw_source="configured"), "subnet_gateway", True),
        (_ent(gw_source="suggested"), _ent(id=2, segment="b", gw_source="suggested"), "same_mac", True),
    ],
)
def test_linked(a, b, reason, linked):
    assert svc._linked(reason, a, b) is linked


def test_edges_collect_every_reason_for_a_pair_under_one_key():
    a, b = _ent(id=2, segment="a"), _ent(id=1, segment="b")
    edges = svc._edges({("same_mac", "x"): [a, b], ("same_hostname", "y"): [b, a]})
    assert edges == {(("device", 1), ("device", 2)): {"same_mac", "same_hostname"}}


def test_edges_compare_every_pair_of_a_bucket():
    members = [_ent(id=1, segment="a"), _ent(id=2, segment="b"), _ent(id=3, segment="c")]
    assert len(svc._edges({("same_mac", "x"): members})) == 3


def test_edges_leave_out_a_bucket_with_nothing_linked():
    assert svc._edges({("same_mac", "x"): [_ent(id=1), _ent(id=2)]}) == {}


def _dev(id: int) -> SimpleNamespace:
    return SimpleNamespace(id=id)


def test_a_cluster_target_is_never_its_own_candidate():
    target = _dev(1)
    edges = {(("device", 1), ("device", 2)): {"same_mac"}}
    found = svc._candidate_reasons(edges, {("device", 1): target, ("device", 2): target})
    assert found == {("device", 2): (target, {"same_mac"})}


def test_a_discovered_address_is_only_ever_a_candidate():
    target = _dev(1)
    found = svc._candidate_reasons({(("device", 1), ("discovered", 5)): {"same_mac"}}, {("device", 1): target})
    assert found == {("discovered", 5): (target, {"same_mac"})}


def test_reasons_add_up_for_the_same_target():
    target = _dev(1)
    edges = {(("device", 1), ("discovered", 5)): {"same_mac"}, (("device", 2), ("discovered", 5)): {"same_hostname"}}
    found = svc._candidate_reasons(edges, {("device", 1): target, ("device", 2): target})
    assert found[("discovered", 5)] == (target, {"same_mac", "same_hostname"})


def test_a_discovered_address_linked_to_two_clusters_keeps_the_first():
    first, second = _dev(1), _dev(2)
    edges = {(("device", 1), ("discovered", 5)): {"same_mac"}, (("device", 2), ("discovered", 5)): {"same_hostname"}}
    found = svc._candidate_reasons(edges, {("device", 1): first, ("device", 2): second})
    assert found[("discovered", 5)] == (first, {"same_mac"})


# --- suggestions -------------------------------------------------------------

async def test_a_device_seen_in_two_vlans_is_suggested_with_all_details(db):
    _, iot = await _vlans(db)
    await _devices(db, _device(LAN_IP, "router"), _device(IOT_IP, "router-iot"))
    [suggestion] = await svc.find_merge_suggestions(db)
    assert suggestion["target_name"] == "router"
    assert suggestion["target_ip"] == LAN_IP
    assert suggestion["candidate"] == {
        "kind": "device", "id": suggestion["candidate"]["id"], "ip": IOT_IP, "name": "router-iot",
        "mac": MAC, "subnet_id": iot.id, "subnet_name": "IoT", "is_online": True,
    }
    assert suggestion["reasons"] == ["same_mac"]


async def test_the_target_is_named_by_its_address_as_a_last_resort(db):
    await _vlans(db)
    await _devices(db, _device(LAN_IP), _device(IOT_IP))
    [suggestion] = await svc.find_merge_suggestions(db)
    assert suggestion["target_name"] == LAN_IP


async def test_an_address_outside_every_subnet_has_no_subnet(db):
    await _vlans(db)
    await _devices(db, _device(LAN_IP, "router"), _device("203.0.113.9", "elsewhere"))
    [suggestion] = await svc.find_merge_suggestions(db)
    assert (suggestion["candidate"]["subnet_id"], suggestion["candidate"]["subnet_name"]) == (None, None)


async def test_dismissed_suggestions_stay_away(db):
    await _vlans(db)
    target, _ = await _devices(db, _device(LAN_IP, "router"), _device(IOT_IP, "router-iot"))
    await svc.dismiss_suggestion(db, target.id, "device", IOT_IP)
    assert await svc.find_merge_suggestions(db) == []


async def test_placeholder_and_already_known_addresses_are_not_suggested(db):
    await _vlans(db)
    target, *_ = await _devices(db, _device(LAN_IP, "router"), _device(IOT_IP, "placeholder", ip_placeholder=True))
    db.add_all([
        DiscoveredHost(ip=LAN_IP, mac=MAC, is_online=True),
        DiscoveredHost(ip="198.51.100.20", mac=MAC, is_online=True, ip_placeholder=True),
    ])
    await db.commit()
    assert await svc.find_merge_suggestions(db) == []
    assert target.interfaces == []


async def test_a_discovered_address_is_suggested_under_its_custom_name(db):
    await _vlans(db)
    await _devices(db, _device(LAN_IP, "router"))
    db.add(DiscoveredHost(ip=IOT_IP, mac=MAC, is_online=True, custom_name="Router IoT", hostname="ignored.lan"))
    await db.commit()
    [suggestion] = await svc.find_merge_suggestions(db)
    assert suggestion["candidate"]["kind"] == "discovered"
    assert suggestion["candidate"]["name"] == "Router IoT"


# --- dismissed list ----------------------------------------------------------

@pytest.mark.parametrize("stored", ["{broken", "5", ""])
async def test_an_unreadable_dismissed_list_counts_as_empty(db, stored):
    db.add(Setting(key=svc.DISMISSED_KEY, value=stored))
    await db.commit()
    assert await svc._load_dismissed(db) == set()


async def test_dismissing_again_extends_the_stored_list(db):
    await svc.dismiss_suggestion(db, 1, "device", "192.0.2.2")
    await svc.dismiss_suggestion(db, 1, "discovered", "192.0.2.1")
    assert await svc._load_dismissed(db) == {"1:device:192.0.2.2", "1:discovered:192.0.2.1"}
    rows = (await db.execute(select(Setting).where(Setting.key == svc.DISMISSED_KEY))).scalars().all()
    assert len(rows) == 1


# --- attach / merge ----------------------------------------------------------

async def test_attach_refuses_the_devices_own_address(db):
    [target] = await _devices(db, _device(LAN_IP, "router"))
    with pytest.raises(InterfaceError) as err:
        await svc.attach_address(db, target, LAN_IP)
    assert err.value.status_code == 409
    assert "primary address" in err.value.detail


async def test_attach_refuses_an_address_that_is_already_an_interface(db):
    [target] = await _devices(db, _device(LAN_IP, "router"))
    await svc.attach_address(db, target, IOT_IP)
    with pytest.raises(InterfaceError, match="already an interface"):
        await svc.attach_address(db, target, IOT_IP)


async def test_attach_points_at_the_device_that_holds_the_address(db):
    target, _ = await _devices(db, _device(LAN_IP, "router"), _device(IOT_IP, "other"))
    with pytest.raises(InterfaceError, match="belongs to device 'other'.*merge that device"):
        await svc.attach_address(db, target, IOT_IP)


async def test_a_device_cannot_be_merged_into_itself(db):
    [target] = await _devices(db, _device(LAN_IP, "router"))
    with pytest.raises(InterfaceError) as err:
        await svc.merge_device_into(db, target, target)
    assert err.value.status_code == 400


async def test_merge_refuses_a_source_whose_address_is_already_an_interface(db):
    target, source = await _devices(db, _device(LAN_IP, "router"), _device(IOT_IP, "dup"))
    db.add(DeviceInterface(device_id=target.id, ip=IOT_IP))
    await db.commit()
    with pytest.raises(InterfaceError, match="already an interface"):
        await svc.merge_device_into(db, target, source)
    assert await db.get(Device, source.id) is not None


@pytest.mark.parametrize(
    "source_name, expected",
    [("Router IoT", "Router IoT"), ("router", None), (IOT_IP, None), ("", None)],
    ids=["own name", "same as target", "just its address", "no name"],
)
async def test_merge_keeps_only_a_name_that_says_something(db, source_name, expected):
    await _vlans(db)
    target, source = await _devices(db, _device(LAN_IP, "router"), _device(IOT_IP, source_name))
    iface = await svc.merge_device_into(db, target, source)
    assert iface.label == expected


async def test_merge_turns_the_source_into_an_interface_and_says_so(db):
    _, iot = await _vlans(db)
    target, source = await _devices(db, _device(LAN_IP, "router"), _device(IOT_IP, "dup", hostname="dup.lan"))
    source_id = source.id
    iface = await svc.merge_device_into(db, target, source)
    assert (iface.device_id, iface.ip, iface.mac, iface.subnet_id, iface.is_online) == (target.id, IOT_IP, MAC, iot.id, True)
    assert await db.get(Device, source_id) is None
    notes = (await db.execute(select(DeviceHistory.message).where(DeviceHistory.device_id == target.id))).scalars().all()
    assert f"Merged dup ({IOT_IP}) as interface of router" in notes


async def test_merge_outside_every_subnet_has_no_subnet(db):
    target, source = await _devices(db, _device(LAN_IP, "router"), _device("203.0.113.9", "dup"))
    assert (await svc.merge_device_into(db, target, source)).subnet_id is None


# --- gateway list ------------------------------------------------------------

async def test_no_subnets_no_gateways(db):
    assert await svc.list_gateways(db) == []


async def test_untagged_networks_come_first_then_by_tag_then_by_name(db):
    db.add_all([
        Subnet(cidr="198.51.100.0/24", name="b", vlan_id=20),
        Subnet(cidr="203.0.113.0/24", name="a", vlan_id=20),
        Subnet(cidr="198.18.0.0/24", name="z", vlan_id=5),
        Subnet(cidr="192.0.2.0/24", name="Main"),
    ])
    await db.commit()
    assert [g["subnet_name"] for g in await svc.list_gateways(db)] == ["Main", "z", "a", "b"]


async def test_a_subnet_without_a_gateway_is_listed_empty(db):
    await _vlans(db)
    with patch("app.services.interface_service.effective_gateway", return_value=None):
        entries = await svc.list_gateways(db)
    assert [(e["gateway_ip"], e["source"]) for e in entries] == [(None, None), (None, None)]
    assert "device_id" not in entries[0]


async def _with_gateway(db) -> tuple[Subnet, str]:
    sub = Subnet(cidr="192.0.2.0/24", name="LAN", gateway_ip="192.0.2.1")
    db.add(sub)
    await db.commit()
    return sub, "192.0.2.1"


async def test_a_gateway_held_by_a_device(db):
    _, ip = await _with_gateway(db)
    [dev] = await _devices(db, _device(ip, "router"))
    [entry] = await svc.list_gateways(db)
    assert entry["gateway_ip"] == ip
    assert entry["source"] is not None
    assert entry["is_enabled"] is True
    assert (entry["device_id"], entry["device_name"], entry["is_primary"], entry["mac"]) == (dev.id, "router", True, MAC)


async def test_a_gateway_held_by_an_interface_names_its_owner(db):
    _, ip = await _with_gateway(db)
    [dev] = await _devices(db, _device(IOT_IP, "router"))
    db.add(DeviceInterface(device_id=dev.id, ip=ip, mac=MAC, is_online=True))
    await db.commit()
    [entry] = await svc.list_gateways(db)
    assert (entry["device_id"], entry["device_name"]) == (dev.id, "router")
    assert entry["interface_id"] is not None
    assert "is_primary" not in entry


async def test_a_gateway_seen_only_as_a_discovered_host(db):
    _, ip = await _with_gateway(db)
    db.add(DiscoveredHost(ip=ip, mac=MAC, is_online=True, hostname="gw.lan"))
    await db.commit()
    [entry] = await svc.list_gateways(db)
    assert (entry["device_name"], entry["mac"], entry["is_online"]) == ("gw.lan", MAC, True)
    assert "device_id" not in entry


async def test_a_gateway_nobody_answers_on(db):
    _, ip = await _with_gateway(db)
    [entry] = await svc.list_gateways(db)
    assert entry["gateway_ip"] == ip
    assert "device_name" not in entry


def test_an_interface_whose_owner_is_gone_has_no_device_name():
    iface = SimpleNamespace(device_id=9, id=3, is_online=True, last_seen=None, mac=MAC)
    assert svc._gateway_holder("192.0.2.1", {}, {"192.0.2.1": iface}, {}, {})["device_name"] is None


def test_a_device_is_named_by_hostname_then_address():
    dev = SimpleNamespace(id=1, display_name="", hostname="gw.lan", ip="192.0.2.1", is_online=False, last_seen=None, mac=None)
    assert svc._gateway_holder("192.0.2.1", {"192.0.2.1": dev}, {}, {}, {})["device_name"] == "gw.lan"
    dev.hostname = None
    assert svc._gateway_holder("192.0.2.1", {"192.0.2.1": dev}, {}, {}, {})["device_name"] == "192.0.2.1"
