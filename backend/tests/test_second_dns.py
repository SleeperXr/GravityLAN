"""A second DNS server: both answers kept per device, the user picks which one names it."""

from unittest.mock import AsyncMock

import dns.message
import pytest

from app.models.device import Device
from app.models.setting import Setting
from app.scanner import hostname
from app.scanner.hostname import choose_hostname


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def test_choose_hostname():
    names = {"1": "nas.lan", "2": "nas.fritz.box"}
    # Automatic: the usual lookup, DNS 2 when it found nothing, then DNS 1
    assert choose_hostname("nas.local", names, None) == "nas.local"
    assert choose_hostname(None, names, None) == "nas.fritz.box"
    assert choose_hostname(None, {"1": "nas.lan", "2": None}, None) == "nas.lan"
    # A picked server wins when it answered, else it falls back like automatic
    assert choose_hostname("nas.local", names, "dns2") == "nas.fritz.box"
    assert choose_hostname("nas.local", names, "dns1") == "nas.lan"
    assert choose_hostname("nas.local", {"1": "nas.lan", "2": None}, "dns2") == "nas.local"
    assert choose_hostname(None, None, "dns1") is None


def test_query_ptr_asks_the_given_server(monkeypatch):
    seen = {}

    class FakeResolver:
        def __init__(self):
            self.nameservers = ["system"]

        def resolve(self, name, kind):
            seen["servers"], seen["kind"] = self.nameservers, kind
            return ["nas.fritz.box."]

    monkeypatch.setattr(hostname.dns.resolver, "Resolver", FakeResolver)
    assert hostname.query_ptr("192.0.2.30", "192.0.2.2") == "nas.fritz.box"
    assert seen == {"servers": ["192.0.2.2"], "kind": "PTR"}

    class Failing(FakeResolver):
        def resolve(self, name, kind):
            raise hostname.dns.resolver.NXDOMAIN()

    monkeypatch.setattr(hostname.dns.resolver, "Resolver", Failing)
    assert hostname.query_ptr("192.0.2.30", None) is None


_QUERY = dns.message.make_query("30.2.0.192.in-addr.arpa.", "PTR")


@pytest.mark.parametrize(
    "error, reason",
    [
        (hostname.dns.resolver.NXDOMAIN(), "no_entry"),
        (hostname.dns.resolver.NoAnswer(), "no_entry"),
        (hostname.dns.resolver.LifetimeTimeout(timeout=2.0, errors=[]), "timeout"),
        (hostname.dns.resolver.NoNameservers(request=_QUERY, errors=[("192.0.2.2", False, 53, "REFUSED", None)]), "refused"),
        (hostname.dns.resolver.NoNameservers(request=_QUERY, errors=[("192.0.2.2", False, 53, "SERVFAIL", None)]), "server_error"),
        (OSError("network unreachable"), "error"),
        # A server address that merely contains the word is not a refusal; an error without an rcode is no server error
        (hostname.dns.resolver.NoNameservers(request=_QUERY, errors=[("fe80::1%REFUSED", False, 53, OSError("no route"), None)]), "error"),
    ],
)
def test_ptr_lookup_says_why_there_is_no_name(monkeypatch, error, reason):
    class Failing:
        def __init__(self):
            self.nameservers = []

        def resolve(self, name, kind):
            raise error

    monkeypatch.setattr(hostname.dns.resolver, "Resolver", Failing)
    assert hostname.ptr_lookup("192.0.2.30", "192.0.2.2") == (None, reason)


@pytest.mark.asyncio
async def test_lookup_dns_names_keeps_the_reasons(monkeypatch):
    answers = {"192.0.2.1": ("nas.lan", None), "192.0.2.2": (None, "no_entry")}
    monkeypatch.setattr(hostname, "ptr_lookup", lambda ip, server: answers[server])
    assert await hostname.lookup_dns_names("192.0.2.30", "192.0.2.1", "192.0.2.2") == {
        "1": "nas.lan", "2": None, "2_reason": "no_entry",
    }


async def _setup(db, secondary: str | None = "192.0.2.2") -> Device:
    db.add(Setting(key="dns.server", value="192.0.2.1", category="scan"))
    if secondary:
        db.add(Setting(key="dns.server_secondary", value=secondary, category="scan"))
    dev = Device(ip="192.0.2.30", display_name="192.0.2.30", mac="aa:bb:cc:dd:ee:30")
    db.add(dev)
    await db.commit()
    return dev


@pytest.mark.asyncio
async def test_refresh_keeps_both_answers_and_the_pick_names_the_device(client, db, auth, monkeypatch):
    dev = await _setup(db)
    monkeypatch.setattr("app.api.devices.resolve_hostname", AsyncMock(return_value="nas.lan"))
    lookup = AsyncMock(return_value={"1": "nas.lan", "2": "nas.fritz.box"})
    monkeypatch.setattr("app.api.devices.lookup_dns_names", lookup)
    monkeypatch.setattr("app.api.devices.get_vendor", lambda mac: None)

    body = (await client.post(f"/api/devices/{dev.id}/refresh-info", headers=auth)).json()
    assert lookup.await_args.args == ("192.0.2.30", "192.0.2.1", "192.0.2.2")
    assert body["dns_names"] == {"1": "nas.lan", "2": "nas.fritz.box"}
    assert (body["hostname"], body["hostname_source"], body["display_name"]) == ("nas.lan", None, "nas")

    # Picking DNS 2 renames the device right away; the display name the device already has stays
    body = (await client.patch(f"/api/devices/{dev.id}", json={"hostname_source": "dns2"}, headers=auth)).json()
    assert (body["hostname"], body["hostname_source"], body["display_name"]) == ("nas.fritz.box", "dns2", "nas")

    # A later refresh keeps the pick
    body = (await client.post(f"/api/devices/{dev.id}/refresh-info", headers=auth)).json()
    assert body["hostname"] == "nas.fritz.box"

    # Back to automatic: the next refresh takes the usual lookup again
    body = (await client.patch(f"/api/devices/{dev.id}", json={"hostname_source": "auto"}, headers=auth)).json()
    assert body["hostname_source"] is None
    body = (await client.post(f"/api/devices/{dev.id}/refresh-info", headers=auth)).json()
    assert body["hostname"] == "nas.lan"


@pytest.mark.asyncio
async def test_without_a_second_dns_nothing_changes(client, db, auth, monkeypatch):
    dev = await _setup(db, secondary=None)
    monkeypatch.setattr("app.api.devices.resolve_hostname", AsyncMock(return_value="nas.lan"))
    lookup = AsyncMock()
    monkeypatch.setattr("app.api.devices.lookup_dns_names", lookup)
    monkeypatch.setattr("app.api.devices.get_vendor", lambda mac: None)

    body = (await client.post(f"/api/devices/{dev.id}/refresh-info", headers=auth)).json()
    lookup.assert_not_awaited()
    assert (body["hostname"], body["dns_names"]) == ("nas.lan", None)

    # A pick without answers to pick from is stored but renames nothing
    body = (await client.patch(f"/api/devices/{dev.id}", json={"hostname_source": "dns2"}, headers=auth)).json()
    assert (body["hostname"], body["hostname_source"]) == ("nas.lan", "dns2")
    assert (await client.patch(f"/api/devices/{dev.id}", json={"hostname_source": "dns3"}, headers=auth)).status_code == 422


@pytest.mark.asyncio
async def test_the_editor_gets_why_a_server_gave_no_name(client, db, auth, monkeypatch):
    dev = await _setup(db)
    monkeypatch.setattr("app.api.devices.resolve_hostname", AsyncMock(return_value="nas.lan"))
    monkeypatch.setattr(
        "app.api.devices.lookup_dns_names", AsyncMock(return_value={"1": "nas.lan", "2": None, "2_reason": "no_entry"})
    )
    monkeypatch.setattr("app.api.devices.get_vendor", lambda mac: None)

    body = (await client.post(f"/api/devices/{dev.id}/refresh-info", headers=auth)).json()
    assert body["dns_names"] == {"1": "nas.lan", "2": None}
    assert body["dns_errors"] == {"2": "no_entry"}

    # Answers stored before reasons existed carry none
    dev.dns_names = '{"1": "nas.lan", "2": null}'
    assert dev.dns_errors == {}


@pytest.mark.asyncio
async def test_broken_stored_names_do_not_break_the_device_list(client, db, auth):
    db.add(Device(ip="192.0.2.30", display_name="x", dns_names='{"1": 42, "2": ["x"], "2_reason": 7}'))
    await db.commit()

    res = await client.get("/api/devices", headers=auth)
    assert res.status_code == 200, res.text
    assert [(d["dns_names"], d["dns_errors"]) for d in res.json()] == [({"1": None, "2": None}, {})]


@pytest.mark.asyncio
async def test_refresh_all_follows_the_pick(client, db, auth, monkeypatch):
    dev = await _setup(db)
    dev.hostname_source = "dns2"
    await db.commit()

    class SameSession:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_exc):
            pass

    monkeypatch.setattr("app.database.async_session", SameSession)
    monkeypatch.setattr("app.scanner.hostname.resolve_hostname", AsyncMock(return_value="nas.lan"))
    monkeypatch.setattr("app.api.devices.lookup_dns_names", AsyncMock(return_value={"1": "nas.lan", "2": "nas.fritz.box"}))
    monkeypatch.setattr("app.scanner.arp.resolve_mac_addresses", AsyncMock())
    monkeypatch.setattr("app.api.devices.get_vendor", lambda mac: None)

    assert (await client.post("/api/devices/refresh-all", headers=auth)).status_code == 200
    await db.refresh(dev)
    assert (dev.hostname, dev.display_name) == ("nas.fritz.box", "nas")


@pytest.mark.asyncio
async def test_removing_dns2_drops_its_answers_and_picks(client, db, auth, monkeypatch):
    dev = await _setup(db)
    dev.dns_names, dev.hostname_source = '{"1": "nas.lan", "2": "nas.fritz.box"}', "dns2"
    await db.commit()

    assert (await client.post("/api/settings", json={"dns.server_secondary": ""}, headers=auth)).status_code == 200
    await db.refresh(dev)
    assert (dev.dns_names, dev.hostname_source) == (None, None)

    # A refresh without DNS 2 also forgets answers kept from it
    dev2 = Device(ip="192.0.2.31", display_name="x", dns_names='{"1": null, "2": "old.fritz.box"}')
    db.add(dev2)
    await db.commit()
    monkeypatch.setattr("app.api.devices.resolve_hostname", AsyncMock(return_value="x.lan"))
    monkeypatch.setattr("app.api.devices.get_vendor", lambda mac: None)
    monkeypatch.setattr("app.scanner.arp.resolve_mac_addresses", AsyncMock())
    body = (await client.post(f"/api/devices/{dev2.id}/refresh-info", headers=auth)).json()
    assert body["dns_names"] is None


@pytest.mark.asyncio
async def test_second_dns_setting_must_be_an_ip(client, auth):
    bad = await client.post("/api/settings", json={"dns.server_secondary": "dns.example; rm -rf /"}, headers=auth)
    assert bad.status_code == 400
    ok = await client.post("/api/settings", json={"dns.server_secondary": "192.0.2.2"}, headers=auth)
    assert ok.status_code == 200, ok.text
    # Empty clears it
    assert (await client.post("/api/settings", json={"dns.server_secondary": ""}, headers=auth)).status_code == 200
