"""Device classification from hostname and open ports, and the services built from those ports."""

import pytest

from app.scanner.classifier import _build_services, _refine_server_subtype, classify_device, is_client_hostname


def names(services: list[dict]) -> list[str]:
    return [s["name"] for s in services]


def classify(hostname: str = "", ports: list[int] | None = None) -> dict | None:
    return classify_device({"ip": "192.0.2.20", "hostname": hostname, "ports": ports or []})


@pytest.mark.parametrize(
    ("hostname", "expected"),
    [
        ("", False),
        ("R123456", True),             # Wortmann/Terra
        ("pf1abc23", True),            # Lenovo serial, any case
        ("DESKTOP-4F2K.lan", True),    # the domain part is ignored
        ("printer-buero", True),
        ("mediaserver", False),
        ("ABCDEFGH", False),           # eight characters but no digit
    ],
)
def test_is_client_hostname(hostname, expected):
    assert is_client_hostname(hostname) is expected


@pytest.mark.parametrize(
    ("hostname", "ports", "expected"),
    [
        ("SRV-SQL01", set(), "Database"),
        ("SRV-BACKUP", set(), "Backup Server"),
        ("SRV-3CX", set(), "Phone System"),
        ("SRV-WEB", set(), "Web Server"),
        ("SRV01", {3389}, "Windows Server"),
        ("SRV01", {22}, "Linux Server"),
        ("SRV01", set(), "Server"),
    ],
)
def test_refine_server_subtype(hostname, ports, expected):
    assert _refine_server_subtype(hostname, ports) == expected


def test_build_services_maps_standard_ports_and_adds_scp():
    services = _build_services({22, 80})

    assert names(services) == ["SSH", "HTTP", "SCP"]
    assert all(s["is_auto_detected"] for s in services)


def test_build_services_generic_web_and_other_ports():
    services = {s["port"]: s for s in _build_services({8443, 8080, 12345})}

    assert services[8443]["protocol"] == "https"
    assert services[8080]["url_template"] == "http://{ip}:8080"
    assert (services[12345]["name"], services[12345]["protocol"]) == ("Port 12345", "tcp")


def test_build_services_lists_each_port_once():
    services = _build_services({8006, 22}, add_specific=["proxmox", "not-a-template"])

    assert [s["port"] for s in services].count(8006) == 1
    assert names(services)[0] == "Proxmox WebUI"


@pytest.mark.parametrize(("firewall", "ports", "expected_ports"), [("sophos", {4444, 4445}, {4444, 4445}), ("securepoint", {11115}, {11115})])
def test_build_services_firewall_admin(firewall, ports, expected_ports):
    assert {s["port"] for s in _build_services(ports, firewall_type=firewall)} == expected_ports


@pytest.mark.parametrize(
    ("hostname", "ports", "device_type", "subtype"),
    [
        ("", [4444], "firewall", "Sophos"),
        ("", [11115], "firewall", "Securepoint"),
        ("fritzbox", [], "firewall", "Router/Firewall"),
        ("", [8006], "server", "Proxmox"),
        ("pve-node1", [], "server", "Proxmox"),
        ("", [902], "server", "ESXi"),
        ("", [9440], "server", "Nutanix"),
        ("vcenter01", [], "server", "Hypervisor"),
        ("", [5001, 445], "server", "Synology"),
        ("diskstation", [5000], "server", "Synology"),
        ("qnap01", [443], "server", "QNAP"),
        ("nas01", [], "server", "NAS"),
        ("", [8123], "server", "Home Assistant"),
        ("", [8081], "server", "ioBroker"),
        ("srv-db01", [], "server", "Database"),
        ("", [80], "webui", "Web Interface"),
        ("", [22], "server", "SSH Device"),
        ("", [3389], "server", "RDP Device"),
        ("", [12345], "unknown", "Unknown"),
        ("", [], "unknown", "Unknown"),
    ],
)
def test_classify_device(hostname, ports, device_type, subtype):
    result = classify(hostname, ports)

    assert (result["device_type"], result["device_subtype"]) == (device_type, subtype)
    assert result["ip"] == "192.0.2.20"


def test_synology_with_https_gets_dsm_over_https():
    services = classify("", [5001, 445])["services"]

    assert services[0]["name"] == "DSM (HTTPS)"
    assert services[0]["port"] == 5001


def test_unknown_device_keeps_its_ports_as_services():
    assert [s["port"] for s in classify("", [12345])["services"]] == [12345]


def test_plain_client_without_ports_is_dropped():
    assert classify("DESKTOP-4F2K", []) is None


def test_missing_hostname_and_ports_are_tolerated():
    result = classify_device({"ip": "192.0.2.21"})

    assert (result["device_type"], result["services"]) == ("unknown", [])


# --- hostname matching: short codes only as a whole name part, the domain is ignored ---

@pytest.mark.parametrize(
    ("hostname", "ports", "device_type", "subtype"),
    [
        ("iphone.fritz.box", [80], "webui", "Web Interface"),        # the router's domain is not the device
        ("ipad-lisa", [22], "server", "SSH Device"),                 # "AD" inside IPAD is no Domain Controller
        ("jonas-pc", [445], "unknown", "Unknown"),                   # "NAS" inside JONAS is no NAS
        ("apple-tv", [80], "webui", "Web Interface"),                # "APP" inside APPLE is no server
        ("canon-mx920", [80], "webui", "Web Interface"),             # "CA" inside CANON is no PKI server
        ("simon-laptop", [22], "server", "SSH Device"),              # "MON" inside SIMON is no monitoring
        ("smartphone-max", [22], "server", "SSH Device"),            # "PHONE" inside a word is no phone system
    ],
)
def test_short_codes_inside_a_word_or_the_domain_do_not_classify(hostname, ports, device_type, subtype):
    result = classify(hostname, ports)
    assert (result["device_type"], result["device_subtype"]) == (device_type, subtype)


@pytest.mark.parametrize(
    ("hostname", "subtype"),
    [
        ("SRV-DC01", "Domain Controller"),
        ("dc01.corp.lan", "Domain Controller"),
        ("srv-ts02", "Terminal Server"),
        ("db1", "Database"),
        ("mon-zabbix", "Monitoring"),
        ("SRVFILE01", "File Server"),     # long patterns still match inside a name
    ],
)
def test_short_codes_as_a_name_part_still_classify(hostname, subtype):
    result = classify(hostname, [22])
    assert (result["device_type"], result["device_subtype"]) == ("server", subtype)


def test_router_names_still_classify_as_firewall():
    assert classify("fritzbox.fritz.box", [80])["device_type"] == "firewall"
    assert classify("usg-pro", [443])["device_type"] == "firewall"
    assert classify("fw-office", [443])["device_type"] == "firewall"


def test_nas_and_hypervisor_names_need_the_whole_part():
    assert classify("nas", [80])["device_subtype"] == "NAS"
    assert classify("pve01", [22])["device_subtype"] == "Proxmox"
    assert classify("xen-host", [22])["device_subtype"] == "Hypervisor"
    assert classify("xenia-pc", [22])["device_subtype"] == "SSH Device"
