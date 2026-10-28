"""Demo networks for ``scripts/dev_demo.py``.

``home()`` is the small homelab the demo always had. ``company()`` is a small company on Linux: a firewall
with eight VLANs, a core stack, aggregation and access switches, a four-node Proxmox cluster with its own
cluster and backup networks, storage, many clients, access points, printers, cameras and a lot of Shellys.

A device row is ``(name, ip, type, group, flags, services, agent profile)``:
- flags: ``is_ap``, ``is_wlan``, ``is_host``, ``virtual_type``, ``parent`` (device name), ``offline``,
  ``old_ip``, ``subtype``, ``vendor``, ``mac``, ``max_ports``
- services: ``[(name, protocol, port, up)]``
- agent profile: ``(os, ram GB, base cpu %, agent version)`` or ``None``
"""

from dataclasses import dataclass, field

# Agent version the company demo reports; older ones show up in the update center
CURRENT_AGENT = "0.3.10"


@dataclass
class Scenario:
    name: str
    domain: str
    devices: list[tuple]
    links: list[tuple]  # (source, target, link type) or (source, target, link type, 'backup')
    subnets: list[tuple[str, str, str, int | None, str | None]]  # key, cidr, name, vlan, gateway
    extra_groups: list[tuple[str, str, int]]
    racks: list[tuple[str, int]]  # name, units
    rack_slots: dict[str, tuple[str, int, int]]  # device -> (rack, top unit, height)
    grid: dict[str, tuple[float, float]]  # device -> (column, row) for the React topology
    router: str
    router_mac: str
    router_interfaces: list[tuple[str, str, int | None]]  # ip, subnet key, vlan
    pending_router_ips: list[str]  # same MAC, waiting as merge suggestion
    interfaces: list[tuple[str, str, str, int | None, str]] = field(default_factory=list)  # device, ip, subnet, vlan, label
    unknown_hosts: list[tuple[str, str | None]] = field(default_factory=list)  # ip, vendor
    outages: dict[str, list[range]] = field(default_factory=dict)  # device -> 5-minute steps (of 288) it was down
    down_events: list[tuple[str, str, int]] = field(default_factory=list)  # device, message, minutes ago
    patches: dict[str, tuple[int, int]] = field(default_factory=dict)  # device -> (available, security)
    reboot_required: set[str] = field(default_factory=set)
    link_colors: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------------------------- home

def home() -> Scenario:
    devices = [
        ("UniFi Gateway", "192.168.100.1", "firewall", "Firewalls", {}, [("SSH", "ssh", 22, True), ("UniFi OS", "https", 443, True)], None),
        ("Core Switch", "192.168.100.2", "webui", "Netzwerk", {}, [("Web UI", "https", 443, True)], None),
        ("AP Obergeschoss", "192.168.100.3", "webui", "Netzwerk", {"is_ap": True}, [("Web UI", "https", 443, True)], None),
        ("AP Erdgeschoss", "192.168.100.4", "webui", "Netzwerk", {"is_ap": True}, [("Web UI", "https", 443, True)], None),
        ("Proxmox", "192.168.100.10", "server", "Server", {"is_host": True}, [("Proxmox", "https", 8006, True), ("SSH", "ssh", 22, True)], ("Debian GNU/Linux 12 (bookworm)", 64, 42, "0.3.5")),
        ("Unraid", "192.168.100.11", "server", "Server", {"is_host": True}, [("Web UI", "http", 80, True), ("SMB", "smb", 445, True), ("SSH", "ssh", 22, True)], ("Slackware 15.0 (Unraid 7.1)", 32, 58, "0.3.4")),
        ("Synology NAS", "192.168.100.12", "nas", "NAS / Storage", {}, [("DSM", "https", 5001, True), ("SMB", "smb", 445, True), ("NFS", "nfs", 2049, True)], ("Synology DSM 7.2", 8, 35, "0.3.4")),
        ("Pi-hole", "192.168.100.13", "server", "Server", {}, [("DNS", "dns", 53, True), ("Admin", "http", 80, True)], ("Raspberry Pi OS 12", 4, 18, "0.3.5")),
        ("Docker VM", "192.168.100.20", "server", "Server", {"virtual_type": "vm", "parent": "Proxmox"}, [("Portainer", "https", 9443, True), ("SSH", "ssh", 22, True)], ("Ubuntu 24.04 LTS", 16, 81, "0.3.5")),
        ("Home Assistant", "192.168.100.21", "webui", "Smart Home", {"virtual_type": "vm", "parent": "Proxmox"}, [("Home Assistant", "http", 8123, True)], None),
        ("Nextcloud", "192.168.100.22", "webui", "Web Interfaces", {"virtual_type": "docker", "parent": "Unraid"}, [("Nextcloud", "https", 443, True)], None),
        ("Grafana", "192.168.100.23", "webui", "Web Interfaces", {"virtual_type": "docker", "parent": "Docker VM"}, [("Grafana", "http", 3000, False)], None),
        ("Drucker", "192.168.100.50", "unknown", "Clients", {}, [("IPP", "ipp", 631, True), ("Web UI", "http", 80, True)], None),
        ("MacBook", "192.168.100.100", "unknown", "Clients", {"is_wlan": True, "old_ip": "192.168.100.140"}, [], None),
        ("iPhone", "192.168.100.101", "unknown", "Clients", {"is_wlan": True, "offline": True}, [], None),
        ("Hue Bridge", "192.168.110.10", "webui", "Smart Home", {}, [("Hue API", "http", 80, True)], None),
        ("Shelly Plug Büro", "192.168.110.11", "webui", "Smart Home", {"is_wlan": True, "offline": True}, [("Web UI", "http", 80, False)], None),
        # A home spread over floors: a switch per floor behind the gateway
        ("Switch Keller", "192.168.100.30", "switch", "Netzwerk", {}, [("Web UI", "http", 80, True)], None),
        ("Switch Obergeschoss", "192.168.100.31", "switch", "Netzwerk", {}, [("Web UI", "http", 80, True)], None),
        ("Switch Wohnzimmer", "192.168.100.5", "switch", "Netzwerk", {}, [("Web UI", "http", 80, True)], None),
        # More guests around the hosts and access points
        ("Windows VM", "192.168.100.26", "webui", "Server", {"virtual_type": "vm", "parent": "Proxmox"}, [("RDP", "rdp", 3389, True)], None),
        ("Uptime Kuma", "192.168.100.24", "webui", "Web Interfaces", {"virtual_type": "docker", "parent": "Docker VM"}, [("Uptime Kuma", "http", 3001, True)], None),
        ("Traefik", "192.168.100.25", "webui", "Web Interfaces", {"virtual_type": "docker", "parent": "Docker VM"}, [("Dashboard", "http", 8080, True)], None),
        ("Jellyfin", "192.168.100.40", "webui", "Web Interfaces", {"virtual_type": "docker", "parent": "Unraid"}, [("Jellyfin", "http", 8096, True)], None),
        ("Immich", "192.168.100.41", "webui", "Web Interfaces", {"virtual_type": "docker", "parent": "Unraid"}, [("Immich", "http", 2283, True)], None),
        ("Vaultwarden", "192.168.100.42", "webui", "Web Interfaces", {"virtual_type": "docker", "parent": "Unraid"}, [("Vaultwarden", "https", 443, True)], None),
        ("Paperless", "192.168.100.43", "webui", "Web Interfaces", {"virtual_type": "docker", "parent": "Unraid"}, [("Paperless", "http", 8000, True)], None),
        ("Pixel 8", "192.168.100.102", "unknown", "Clients", {"is_wlan": True}, [], None),
        ("iPad", "192.168.100.103", "unknown", "Clients", {"is_wlan": True}, [], None),
        ("Fernseher Wohnzimmer", "192.168.100.104", "unknown", "Clients", {"is_wlan": True}, [], None),
        ("Echo Küche", "192.168.110.12", "webui", "Smart Home", {"is_wlan": True}, [], None),
    ]
    # The servers sit in one rack, top to bottom (top unit, height); the two hosts take 2 U each
    rack_slots = {
        "UniFi Gateway": ("Keller-Rack", 20, 1), "Proxmox": ("Keller-Rack", 18, 2), "Unraid": ("Keller-Rack", 16, 2),
        "Synology NAS": ("Keller-Rack", 14, 1), "Pi-hole": ("Keller-Rack", 13, 1),
    }
    return Scenario(
        name="home",
        domain="lan",
        devices=devices,
        links=[("UniFi Gateway", "Core Switch", "10GbE"), ("Core Switch", "Proxmox", "10GbE"), ("Core Switch", "Unraid", "10GbE"),
               ("Core Switch", "Synology NAS", "2.5GbE"), ("Core Switch", "Pi-hole", "1GbE"), ("Core Switch", "Drucker", "1GbE"),
               # The floors: basement switch, then one switch upstairs and one in the living room
               ("UniFi Gateway", "Switch Keller", "2.5GbE"), ("Switch Keller", "Switch Obergeschoss", "2.5GbE"),
               ("Switch Keller", "Switch Wohnzimmer", "2.5GbE"), ("Switch Obergeschoss", "AP Obergeschoss", "2.5GbE"),
               ("Switch Wohnzimmer", "AP Erdgeschoss", "1GbE"), ("Proxmox", "Docker VM", "10GbE")],
        subnets=[("lan", "192.168.100.0/24", "Home LAN", None, "192.168.100.1"),
                 ("iot", "192.168.110.0/24", "IoT", 110, "192.168.110.1"),
                 ("guest", "192.168.120.0/24", "Gäste", 120, None)],
        extra_groups=[("Netzwerk", "network", 1), ("Smart Home", "home", 5), ("Clients", "laptop", 6)],
        racks=[("Keller-Rack", 24)],
        rack_slots=rack_slots,
        # Tidy tree for the React topology (column, row); GravityUI's orbit map lays itself out
        grid={
            "UniFi Gateway": (5.5, 0), "Core Switch": (2.5, 1), "Switch Keller": (9, 1),
            "Proxmox": (0.5, 2), "Unraid": (2.5, 2), "Synology NAS": (4, 2), "Pi-hole": (5, 2), "Drucker": (6, 2),
            "Switch Obergeschoss": (8, 2), "Switch Wohnzimmer": (10, 2),
            "Docker VM": (0, 3), "Home Assistant": (1, 3), "Windows VM": (1, 4),
            "Grafana": (0, 4), "Uptime Kuma": (0, 5), "Traefik": (0, 6),
            "Nextcloud": (2, 3), "Jellyfin": (3, 3), "Immich": (2, 4), "Vaultwarden": (3, 4), "Paperless": (2.5, 5),
            "AP Obergeschoss": (8, 3), "AP Erdgeschoss": (10, 3),
            "MacBook": (7.5, 4), "iPhone": (8.5, 4), "Pixel 8": (9.5, 4), "iPad": (10.5, 4), "Fernseher Wohnzimmer": (10, 5),
            "Hue Bridge": (11.5, 2), "Shelly Plug Büro": (11.5, 3), "Echo Küche": (11.5, 4),
        },
        router="UniFi Gateway",
        router_mac="f4:e2:c6:00:00:01",  # one MAC on every VLAN, like most consumer and UniFi routers
        router_interfaces=[("192.168.110.1", "iot", 110)],
        pending_router_ips=["192.168.120.1"],
        unknown_hosts=[("192.168.100.60", None), ("192.168.100.61", None), ("192.168.100.142", None),
                       ("192.168.110.30", "Espressif Inc."), ("192.168.110.31", "Espressif Inc.")],
        # The upstairs access point had a short outage this morning
        outages={"AP Obergeschoss": [range(200, 204)]},
        down_events=[("Grafana", "Service Grafana (3000) is down", 25)],
        patches={d[0]: (7, 2) for d in devices if d[6] and d[6][3] == "0.3.4"},
        reboot_required={"Unraid"},
        # One colour per link speed on the orbit map, as many homelabs set it up
        link_colors={"10GbE": "#dfe6ee", "2.5GbE": "#3db8f5", "1GbE": "#a6e35b", "WLAN": "#2ec4a6"},
    )


# ------------------------------------------------------------------------------------------ company

_DEBIAN = "Debian GNU/Linux 12 (bookworm)"
_UBUNTU = "Ubuntu 24.04.1 LTS"
_PVE = "Debian GNU/Linux 12 (bookworm) · Proxmox VE 8.2"
_WEB = [("Web UI", "https", 443, True)]
_SSH = ("SSH", "ssh", 22, True)


def _mac(n: int) -> str:
    return "02:47:4c:{:02x}:{:02x}:{:02x}".format((n >> 16) & 255, (n >> 8) & 255, n & 255)


def company() -> Scenario:
    devices: list[tuple] = []
    links: list[tuple[str, str, str]] = []
    interfaces: list[tuple[str, str, str, int | None, str]] = []

    def add(name, ip, dtype, group, flags=None, services=(), profile=None):
        devices.append((name, ip, dtype, group, dict(flags or {}), list(services), profile))

    def link(a, b, kind, role="primary"):
        links.append((a, b, kind) if role == "primary" else (a, b, kind, role))

    # --- Core network (management VLAN 10) -----------------------------------------------------
    add("fw-01", "10.20.10.1", "firewall", "Firewalls", {"subtype": "nftables / keepalived", "vendor": "Supermicro", "max_ports": 8},
        [_SSH, ("Web UI", "https", 443, True)], (_DEBIAN, 16, 14, CURRENT_AGENT))
    for name, ip in (("Core-Switch 01", "10.20.10.2"), ("Core-Switch 02", "10.20.10.3")):
        add(name, ip, "switch", "Netzwerk", {"subtype": "Core (Stack)", "vendor": "Juniper", "max_ports": 48}, [_SSH, *_WEB])
    link("fw-01", "Core-Switch 01", "Fiber")
    link("Core-Switch 01", "Core-Switch 02", "Fiber")

    aggregation = {
        "Agg Serverraum": ("10.20.10.5", "Core-Switch 01"),
        "Agg Verwaltung": ("10.20.10.6", "Core-Switch 02"),
        "Agg Lager": ("10.20.10.7", "Core-Switch 02"),
    }
    for name, (ip, core) in aggregation.items():
        add(name, ip, "switch", "Netzwerk", {"subtype": "Aggregation", "vendor": "Juniper", "max_ports": 24}, [_SSH, *_WEB])
        link(core, name, "Fiber")

    access = {
        "ToR Rack A": ("10.20.10.10", "Agg Serverraum", "10GbE"),
        "ToR Rack B": ("10.20.10.11", "Agg Serverraum", "10GbE"),
        "Access EG": ("10.20.10.20", "Agg Verwaltung", "10GbE"),
        "Access OG1": ("10.20.10.21", "Agg Verwaltung", "10GbE"),
        "Access OG2": ("10.20.10.22", "Agg Verwaltung", "10GbE"),
        "Access Lager": ("10.20.10.23", "Agg Lager", "Fiber"),
        "Access Werkstatt": ("10.20.10.24", "Agg Lager", "10GbE"),
    }
    for name, (ip, uplink, kind) in access.items():
        tor = name.startswith("ToR")
        add(name, ip, "switch", "Netzwerk",
            {"subtype": "Top of Rack" if tor else "Access PoE+", "vendor": "Juniper" if tor else "Aruba", "max_ports": 48},
            [_SSH, *_WEB])
        link(uplink, name, kind)

    aps = {
        "AP EG Empfang": ("10.20.10.30", "Access EG"), "AP EG Besprechung": ("10.20.10.31", "Access EG"),
        "AP OG1 Ost": ("10.20.10.32", "Access OG1"), "AP OG1 West": ("10.20.10.33", "Access OG1"),
        "AP OG2 Ost": ("10.20.10.34", "Access OG2"), "AP OG2 West": ("10.20.10.35", "Access OG2"),
        "AP Lager Halle": ("10.20.10.36", "Access Lager"), "AP Lager Außen": ("10.20.10.37", "Access Lager"),
        "AP Werkstatt": ("10.20.10.38", "Access Werkstatt"),
    }
    for name, (ip, switch) in aps.items():
        add(name, ip, "webui", "Netzwerk", {"is_ap": True, "subtype": "Access Point Wi-Fi 6E", "vendor": "Aruba"}, _WEB)
        link(switch, name, "2.5GbE")

    add("USV Serverraum", "10.20.10.50", "webui", "Netzwerk", {"subtype": "USV (NUT)", "vendor": "APC"}, [("NUT", "nut", 3493, True), ("Web UI", "http", 80, True)])
    link("ToR Rack A", "USV Serverraum", "1GbE")

    # --- Proxmox cluster (server VLAN 20, cluster VLAN 30, backup VLAN 40) ---------------------
    nodes = {"pve-01": ("ToR Rack A", 41), "pve-02": ("ToR Rack A", 47), "pve-03": ("ToR Rack B", 55), "pve-04": ("ToR Rack B", 38)}
    for i, (name, (tor, cpu)) in enumerate(nodes.items(), start=1):
        add(name, f"10.20.20.1{i}", "server", "Server", {"is_host": True, "subtype": "Proxmox VE", "vendor": "Supermicro", "max_ports": 6},
            [("Proxmox", "https", 8006, True), _SSH, *([("Ceph Dashboard", "https", 8443, True)] if i == 1 else [])], (_PVE, 256, cpu, CURRENT_AGENT))
        link(tor, name, "10GbE")
        interfaces.append((name, f"10.20.30.1{i}", "cluster", 30, "Corosync / Ceph"))
        interfaces.append((name, f"10.20.40.1{i}", "backup", 40, "Backup"))

    add("pbs-01", "10.20.40.20", "server", "Server", {"subtype": "Proxmox Backup Server", "vendor": "Supermicro"},
        [("Backup Server", "https", 8007, True), _SSH], (_DEBIAN, 64, 22, CURRENT_AGENT))
    link("ToR Rack B", "pbs-01", "10GbE")
    interfaces.append(("pbs-01", "10.20.20.20", "server", 20, "Management"))

    add("TrueNAS", "10.20.20.30", "nas", "NAS / Storage", {"subtype": "TrueNAS SCALE", "vendor": "iXsystems"},
        [("Web UI", "https", 443, True), ("SMB", "smb", 445, True), ("NFS", "nfs", 2049, True), _SSH],
        ("TrueNAS SCALE 24.10 (Debian 12)", 128, 31, CURRENT_AGENT))
    link("ToR Rack A", "TrueNAS", "10GbE")
    interfaces.append(("TrueNAS", "10.20.40.30", "backup", 40, "Replikation"))

    add("Archiv-NAS", "10.20.40.31", "nas", "NAS / Storage", {"subtype": "Synology RS1221+", "vendor": "Synology"},
        [("DSM", "https", 5001, True), ("Hyper Backup", "https", 6281, True)], ("Synology DSM 7.2.2 (Linux 4.4)", 32, 17, "0.3.9"))
    link("ToR Rack B", "Archiv-NAS", "10GbE")

    # Guests on the nodes: VMs and containers
    vm = lambda parent, **extra: {"virtual_type": "vm", "parent": parent, **extra}  # noqa: E731
    ct = lambda parent, **extra: {"virtual_type": "docker", "parent": parent, **extra}  # noqa: E731
    add("dc-01", "10.20.20.101", "server", "Server", vm("pve-01", subtype="Samba AD DC"), [("LDAP", "ldap", 389, True), ("Kerberos", "kerberos", 88, True), _SSH], (_UBUNTU, 8, 12, CURRENT_AGENT))
    add("dns-01", "10.20.20.102", "server", "Server", vm("pve-01", subtype="Bind9"), [("DNS", "dns", 53, True), _SSH], (_DEBIAN, 2, 6, CURRENT_AGENT))
    add("gitlab", "10.20.20.103", "webui", "Web Interfaces", vm("pve-01", subtype="GitLab CE"), [("GitLab", "https", 443, True), _SSH], (_UBUNTU, 16, 46, CURRENT_AGENT))
    add("mail-gw", "10.20.90.10", "webui", "DMZ", vm("pve-01", subtype="Mailcow"), [("SMTP", "smtp", 25, True), ("Webmail", "https", 443, True)])
    add("nextcloud", "10.20.20.111", "webui", "Web Interfaces", vm("pve-02", subtype="Nextcloud Hub"), [("Nextcloud", "https", 443, True), _SSH], (_DEBIAN, 16, 28, CURRENT_AGENT))
    add("postgres-01", "10.20.20.112", "server", "Server", vm("pve-02", subtype="PostgreSQL 16"), [("PostgreSQL", "postgres", 5432, True), _SSH], (_DEBIAN, 32, 37, CURRENT_AGENT))
    add("erp", "10.20.20.113", "webui", "Web Interfaces", vm("pve-02", subtype="Odoo 17"), [("Odoo", "http", 8069, False), _SSH])
    add("web-01", "10.20.90.12", "webui", "DMZ", vm("pve-02", subtype="Nginx"), [("HTTPS", "https", 443, True)])
    add("docker-01", "10.20.20.120", "server", "Server", vm("pve-03", subtype="Docker Host"), [("Portainer", "https", 9443, True), _SSH], (_DEBIAN, 32, 63, CURRENT_AGENT))
    add("monitoring", "10.20.20.121", "webui", "Web Interfaces", vm("pve-03", subtype="Zabbix 7"), [("Zabbix", "https", 443, True), _SSH], (_UBUNTU, 8, 33, CURRENT_AGENT))
    for i, role in enumerate(("master", "worker-1", "worker-2"), start=1):
        add(f"k3s-{role}", f"10.20.20.13{i}", "server", "Server", vm("pve-03", subtype="k3s"), [("Kubernetes API", "https", 6443, True), _SSH], (_DEBIAN, 16, 44 + 6 * i, CURRENT_AGENT))
    add("jumphost", "10.20.20.143", "server", "Server", vm("pve-04", subtype="Bastion"), [_SSH], (_DEBIAN, 2, 4, CURRENT_AGENT))
    add("iot-gw", "10.20.60.10", "webui", "IoT", vm("pve-04", subtype="Home Assistant OS"), [("Home Assistant", "http", 8123, True)])
    add("frigate", "10.20.60.12", "webui", "IoT", vm("pve-04", subtype="Frigate NVR"), [("Frigate", "http", 5000, True)])
    add("mqtt", "10.20.60.11", "webui", "IoT", ct("pve-04", subtype="Mosquitto (LXC)"), [("MQTT", "mqtt", 1883, True)])
    add("netbox", "10.20.20.141", "webui", "Web Interfaces", ct("pve-04", subtype="NetBox (LXC)"), [("NetBox", "https", 443, True)])
    for name, ip, svc, port, up in (("grafana", "10.20.20.122", "Grafana", 3000, True), ("uptime-kuma", "10.20.20.123", "Uptime Kuma", 3001, True),
                                    ("vaultwarden", "10.20.20.142", "Vaultwarden", 443, True), ("wiki", "10.20.20.114", "BookStack", 6875, True)):
        add(name, ip, "webui", "Web Interfaces", ct("docker-01"), [(svc, "https" if port == 443 else "http", port, up)])
    add("traefik", "10.20.90.11", "webui", "DMZ", ct("docker-01", subtype="Reverse Proxy"), [("Dashboard", "http", 8080, True), ("HTTPS", "https", 443, True)])

    # --- Offices: wired workstations, printers, laptops and phones on Wi-Fi (client VLAN 50) ----
    floors = {"EG": ("Access EG", ["AP EG Empfang", "AP EG Besprechung"]),
              "OG1": ("Access OG1", ["AP OG1 Ost", "AP OG1 West"]),
              "OG2": ("Access OG2", ["AP OG2 Ost", "AP OG2 West"]),
              "Lager": ("Access Lager", ["AP Lager Halle", "AP Lager Außen"]),
              "Werkstatt": ("Access Werkstatt", ["AP Werkstatt"])}
    desks = [("empfang", "EG", 1), ("gf", "OG2", 1), ("buchhaltung", "OG1", 3), ("vertrieb", "OG1", 4),
             ("entwicklung", "OG2", 6), ("lager", "Lager", 2), ("werkstatt", "Werkstatt", 2)]
    host = 20
    for dept, floor, count in desks:
        for n in range(1, count + 1):
            host += 1
            name = f"ws-{dept}-{n:02d}"
            agent = (("Fedora Linux 40 (Workstation)", 32, 24 + 7 * n, CURRENT_AGENT) if dept == "entwicklung" and n <= 3 else None)
            add(name, f"10.20.50.{host}", "unknown", "Clients", {"subtype": "Linux Workstation", "vendor": "Lenovo"}, [_SSH] if agent else [], agent)
            link(floors[floor][0], name, "1GbE")

    printers = [("Drucker EG", "EG", "Brother"), ("Drucker OG1", "OG1", "Kyocera"), ("Farbdrucker OG2", "OG2", "HP"),
                ("Plotter Werkstatt", "Werkstatt", "Canon"), ("Etikettendrucker Lager", "Lager", "Zebra")]
    for i, (name, floor, vendor) in enumerate(printers):
        add(name, f"10.20.50.{200 + i}", "webui", "Drucker", {"subtype": "Drucker", "vendor": vendor, "offline": name == "Plotter Werkstatt"},
            [("IPP", "ipp", 631, True), ("Web UI", "http", 80, True)])
        link(floors[floor][0], name, "1GbE")

    wireless = ([(f"nb-vertrieb-{n:02d}", "OG1", "Linux Notebook", "Dell") for n in range(1, 6)]
                + [(f"nb-entwicklung-{n:02d}", "OG2", "Linux Notebook", "Framework") for n in range(1, 5)]
                + [(f"Diensthandy {n:02d}", floor, "Android", "Google") for n, floor in enumerate(["EG", "OG1", "OG1", "OG2", "OG2", "Lager", "Werkstatt"], start=1)]
                + [(f"Scanner Lager {n}", "Lager", "Handscanner (Android)", "Zebra") for n in range(1, 4)]
                + [("Tablet Werkstatt", "Werkstatt", "Android", "Samsung"), ("Konferenz-Display", "EG", "Linux Kiosk", "Raspberry Pi")])
    for i, (name, floor, subtype, vendor) in enumerate(wireless):
        offline = name in ("Diensthandy 06", "nb-vertrieb-05")
        flags = {"is_wlan": True, "subtype": subtype, "vendor": vendor, "offline": offline}
        if name == "nb-entwicklung-02":
            flags["old_ip"] = "10.20.50.188"
        add(name, f"10.20.50.{100 + i}", "unknown", "Clients", flags)
        ap_list = floors[floor][1]
        link(ap_list[i % len(ap_list)], name, "WLAN")

    # --- IoT (VLAN 60): Shellys everywhere, cameras, building control ---------------------------
    shellys = [("Licht Empfang", "EG", "Shelly Plus 1PM"), ("Licht Besprechung", "EG", "Shelly Plus 2PM"), ("Rollo Besprechung", "EG", "Shelly Plus 2PM"),
               ("Kaffeemaschine", "EG", "Shelly Plug S"), ("Licht Büro Ost", "OG1", "Shelly Plus 1PM"), ("Licht Büro West", "OG1", "Shelly Plus 1PM"),
               ("Heizung OG1", "OG1", "Shelly TRV"), ("Drucker-Steckdose OG1", "OG1", "Shelly Plug S"), ("Licht Entwicklung", "OG2", "Shelly Plus 1PM"),
               ("Rollo GF", "OG2", "Shelly Plus 2PM"), ("Klima GF", "OG2", "Shelly Plus 1"), ("Temperatur Serverraum", "EG", "Shelly H&T"),
               ("Hallenlicht 1", "Lager", "Shelly Pro 4PM"), ("Hallenlicht 2", "Lager", "Shelly Pro 4PM"), ("Rolltor Lager", "Lager", "Shelly Plus 1"),
               ("Außenlicht Hof", "Lager", "Shelly Plus 1PM"), ("Kompressor", "Werkstatt", "Shelly Pro 1PM"), ("Absaugung", "Werkstatt", "Shelly Pro 2PM"),
               ("Lüftung Werkstatt", "Werkstatt", "Shelly Plus 1"), ("Ladestation E-Auto", "Lager", "Shelly Pro 3EM"), ("Tür-Sensor Lager", "Lager", "Shelly Door/Window 2"),
               ("Wassermelder Serverraum", "EG", "Shelly Flood")]
    for i, (where, floor, model) in enumerate(shellys):
        name = f"Shelly {where}"
        wired = model.startswith("Shelly Pro")
        flags = {"subtype": model, "vendor": "Shelly (Allterco)", "is_wlan": not wired, "offline": where in ("Rolltor Lager", "Wassermelder Serverraum")}
        if where == "Kaffeemaschine":
            flags["old_ip"] = "10.20.60.199"
        add(name, f"10.20.60.{50 + i}", "webui", "IoT", flags, [("Web UI", "http", 80, not flags["offline"])])
        if wired:
            link(floors[floor][0], name, "1GbE")
        else:
            ap_list = floors[floor][1]
            link(ap_list[i % len(ap_list)], name, "WLAN")

    cameras = [("Kamera Eingang", "EG"), ("Kamera Parkplatz", "Lager"), ("Kamera Lager Tor", "Lager"), ("Kamera Halle", "Lager"), ("Kamera Werkstatt", "Werkstatt")]
    for i, (name, floor) in enumerate(cameras):
        add(name, f"10.20.60.{20 + i}", "webui", "IoT", {"subtype": "IP-Kamera (PoE)", "vendor": "Reolink", "offline": name == "Kamera Parkplatz"},
            [("RTSP", "rtsp", 554, True), ("Web UI", "http", 80, True)])
        link(floors[floor][0], name, "1GbE")
    add("Zutrittskontrolle", "10.20.60.30", "webui", "IoT", {"subtype": "Türcontroller", "vendor": "Siemens"}, _WEB)
    link("Access EG", "Zutrittskontrolle", "1GbE")
    add("Wetterstation Dach", "10.20.60.31", "webui", "IoT", {"subtype": "Wetterstation", "vendor": "Ecowitt", "is_wlan": True}, [("Web UI", "http", 80, True)])
    link("AP Lager Außen", "Wetterstation Dach", "WLAN")

    # --- Redundancy: standby paths that take over when a primary uplink fails ------------------
    # Agg Lager deliberately has no second path, so it stays a single point of failure to look at.
    link("fw-01", "Core-Switch 02", "Fiber", "backup")
    link("Core-Switch 01", "Agg Verwaltung", "Fiber", "backup")
    link("Core-Switch 02", "Agg Serverraum", "Fiber", "backup")
    for node, tor in (("pve-01", "ToR Rack B"), ("pve-02", "ToR Rack B"), ("pve-03", "ToR Rack A"), ("pve-04", "ToR Rack A")):
        link(tor, node, "10GbE", "backup")
    link("ToR Rack B", "TrueNAS", "10GbE", "backup")

    # --- Guest Wi-Fi (VLAN 70) ------------------------------------------------------------------
    guests = [("Gast iPhone", "AP EG Besprechung"), ("Gast Laptop 1", "AP EG Besprechung"), ("Gast Laptop 2", "AP EG Besprechung"),
              ("Gast Android", "AP EG Empfang"), ("Gast iPad", "AP EG Empfang"), ("Lieferant Scanner", "AP Lager Halle")]
    for i, (name, ap) in enumerate(guests):
        add(name, f"10.20.70.{100 + i}", "unknown", "Gäste", {"is_wlan": True, "subtype": "Gastgerät", "offline": name == "Gast Laptop 2"})
        link(ap, name, "WLAN")

    for i, d in enumerate(devices):
        d[4].setdefault("mac", _mac(i + 1))

    rack_slots = {
        # Server room, rack A: edge, core and the first two nodes plus storage
        "fw-01": ("Serverraum Rack A", 42, 1), "Core-Switch 01": ("Serverraum Rack A", 40, 1), "Core-Switch 02": ("Serverraum Rack A", 39, 1),
        "Agg Serverraum": ("Serverraum Rack A", 38, 1), "ToR Rack A": ("Serverraum Rack A", 36, 1),
        "pve-01": ("Serverraum Rack A", 32, 2), "pve-02": ("Serverraum Rack A", 29, 2), "TrueNAS": ("Serverraum Rack A", 24, 4),
        "USV Serverraum": ("Serverraum Rack A", 4, 3),
        # Rack B: second ToR, nodes 3 and 4, backup
        "ToR Rack B": ("Serverraum Rack B", 42, 1), "pve-03": ("Serverraum Rack B", 36, 2), "pve-04": ("Serverraum Rack B", 33, 2),
        "pbs-01": ("Serverraum Rack B", 28, 2), "Archiv-NAS": ("Serverraum Rack B", 24, 2),
        # Floor distribution and warehouse
        "Agg Verwaltung": ("Netzwerkschrank Verwaltung", 24, 1), "Access EG": ("Netzwerkschrank Verwaltung", 22, 1),
        "Access OG1": ("Netzwerkschrank Verwaltung", 21, 1), "Access OG2": ("Netzwerkschrank Verwaltung", 20, 1),
        "Agg Lager": ("Verteiler Lager", 12, 1), "Access Lager": ("Verteiler Lager", 10, 1), "Access Werkstatt": ("Verteiler Lager", 9, 1),
    }

    vlans = [("mgmt", 10, "Management"), ("server", 20, "Server"), ("cluster", 30, "Cluster (Corosync/Ceph)"), ("backup", 40, "Backup"),
             ("clients", 50, "Clients"), ("iot", 60, "IoT"), ("guest", 70, "Gast-WLAN"), ("dmz", 90, "DMZ")]
    routed = {"server", "backup", "clients", "iot", "dmz"}  # the cluster VLAN is not routed; the guest gateway waits as merge suggestion

    return Scenario(
        name="company",
        domain="musterfirma.lan",
        devices=devices,
        links=links,
        subnets=[(key, f"10.20.{vlan}.0/24", label, vlan, f"10.20.{vlan}.1" if key != "cluster" else None) for key, vlan, label in vlans],
        extra_groups=[("Netzwerk", "network", 1), ("DMZ", "shield", 4), ("Drucker", "printer", 5), ("IoT", "home", 6),
                      ("Clients", "laptop", 7), ("Gäste", "users", 8)],
        racks=[("Serverraum Rack A", 42), ("Serverraum Rack B", 42), ("Netzwerkschrank Verwaltung", 24), ("Verteiler Lager", 12)],
        rack_slots=rack_slots,
        grid=tree_grid(devices, links, root="fw-01"),
        router="fw-01",
        router_mac="02:47:4c:00:00:01",
        router_interfaces=[(f"10.20.{vlan}.1", key, vlan) for key, vlan, _ in vlans if key in routed],
        pending_router_ips=["10.20.70.1"],
        interfaces=interfaces,
        unknown_hosts=[("10.20.60.240", "Espressif Inc."), ("10.20.60.241", "Espressif Inc."), ("10.20.60.242", "Tuya Smart"),
                       ("10.20.50.230", None), ("10.20.70.150", "Apple, Inc."), ("10.20.70.151", None)],
        # The outdoor access point keeps dropping: three short outages today
        outages={"AP Lager Außen": [range(150, 152), range(205, 208), range(270, 271)], "Access Werkstatt": [range(96, 98)]},
        down_events=[("erp", "Service Odoo (8069) is down", 12)],
        patches={"pve-02": (12, 3), "Archiv-NAS": (5, 1), "ws-entwicklung-02": (23, 6), "gitlab": (4, 0), "pbs-01": (2, 0)},
        reboot_required={"pve-03", "ws-entwicklung-02"},
        link_colors={"Fiber": "#f5a524", "10GbE": "#dfe6ee", "2.5GbE": "#3db8f5", "1GbE": "#a6e35b", "WLAN": "#2ec4a6"},
    )


def tree_grid(devices: list[tuple], links: list[tuple], root: str) -> dict[str, tuple[float, float]]:
    """(column, row) per device for the React topology: a tidy tree from `root` over primary links, then guests under their host."""
    adjacency: dict[str, list[str]] = {}
    for a, b, *_rest in (l for l in links if len(l) < 4):
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
    for d in devices:
        parent = d[4].get("parent")
        if parent:
            adjacency.setdefault(parent, []).append(d[0])

    children: dict[str, list[str]] = {}
    seen = {root}
    queue = [root]
    while queue:
        node = queue.pop(0)
        for nxt in adjacency.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                children.setdefault(node, []).append(nxt)
                queue.append(nxt)

    grid: dict[str, tuple[float, float]] = {}
    next_col = [0.0]

    def place(node: str, depth: int) -> float:
        kids = children.get(node, [])
        if not kids:
            col = next_col[0]
            next_col[0] += 1
        else:
            cols = [place(k, depth + 1) for k in kids]
            col = (cols[0] + cols[-1]) / 2
        grid[node] = (col, depth)
        return col

    place(root, 0)
    for d in devices:  # nothing should be unreachable; if it is, it lands on the top row
        if d[0] not in grid:
            grid[d[0]] = (next_col[0], 0)
            next_col[0] += 1
    return grid


SCENARIOS = {"home": home, "company": company}
