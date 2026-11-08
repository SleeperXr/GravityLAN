"""The DNS answers kept on a device, read the same way everywhere."""

import pytest

from app.api.devices import _set_hostname_source
from app.dns_answers import stored_dns_answers
from app.models.device import Device, DeviceInterface
from app.schemas.device import DeviceResponse

UNUSABLE = [None, "", "{broken", "[1, 2]", '"nas.lan"', "42"]


def _device(dns_names: str | None) -> Device:
    return Device(ip="192.0.2.1", display_name="kept", hostname="old.lan", dns_names=dns_names)


def test_stored_answers_are_returned_as_they_are():
    assert stored_dns_answers('{"1": "nas.lan", "2": null, "2_reason": "timeout"}') == {
        "1": "nas.lan", "2": None, "2_reason": "timeout",
    }


@pytest.mark.parametrize("raw", UNUSABLE)
def test_anything_but_a_json_object_counts_as_no_answers(raw):
    assert stored_dns_answers(raw) is None


@pytest.mark.parametrize("raw", UNUSABLE)
def test_device_has_no_errors_without_usable_answers(raw):
    assert _device(raw).dns_errors is None


def test_device_errors_keep_only_text_reasons_of_known_servers():
    raw = '{"1_reason": "refused", "2_reason": 7, "3_reason": "timeout"}'
    assert _device(raw).dns_errors == {"1": "refused"}


@pytest.mark.parametrize("raw", UNUSABLE[1:])
def test_response_shows_unusable_text_as_not_asked(raw):
    assert DeviceResponse._parse_dns_names(raw) is None


def test_response_cleans_names_and_accepts_parsed_values():
    expected = {"1": "nas.lan", "2": None}
    assert DeviceResponse._parse_dns_names('{"1": "nas.lan", "2": 42, "2_reason": "x"}') == expected
    assert DeviceResponse._parse_dns_names({"1": "nas.lan"}) == expected


def test_picking_a_server_that_answered_sets_the_hostname():
    device = _device('{"1": "nas.lan"}')
    _set_hostname_source(device, "dns1")
    assert (device.hostname_source, device.hostname) == ("dns1", "nas.lan")


@pytest.mark.parametrize("raw", [*UNUSABLE, '{"2": "other.lan"}', "{}"])
def test_picking_a_server_without_an_answer_keeps_the_hostname(raw):
    device = _device(raw)
    _set_hostname_source(device, "dns1")
    assert (device.hostname_source, device.hostname) == ("dns1", "old.lan")


def test_an_unknown_source_means_automatic():
    device = _device('{"1": "nas.lan"}')
    _set_hostname_source(device, "dns3")
    assert (device.hostname_source, device.hostname) == (None, "old.lan")


def test_interface_prefers_its_own_vlan_tag():
    assert DeviceInterface(ip="192.0.2.2", vlan_id=7).effective_vlan_id == 7
