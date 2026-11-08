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
CURRENT_AGENT = "0.3.11"


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
    # Rack equipment: (name, rack, kind, top unit, height, ports, port kind)
    rack_items: list[tuple] = field(default_factory=list)
    # Ports of devices: device name -> (count, kind)
    port_counts: dict[str, tuple] = field(default_factory=dict)
    # Cables: (owner, port number, owner, port number, cable type); owners are device or rack item names
    cables: list[tuple] = field(default_factory=list)


@dataclass
class DeviceSpec:
    """Parameter object specifying a device row before insertion."""

    name: str
    ip: str
    dtype: str
    group: str
    flags: dict = field(default_factory=dict)
    services: list | tuple = field(default_factory=list)
    profile: tuple | None = None

    def to_row(self) -> tuple:
        return (self.name, self.ip, self.dtype, self.group, dict(self.flags), list(self.services), self.profile)


# --------------------------------------------------------------------------------------------- home

def _home_devices() -> list[tuple]:
    """Device catalogue for the homelab demo network."""
    return [
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


def home() -> Scenario:
    devices = _home_devices()
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
        router_mac="f4:e2:c6:00:00:01",
        router_interfaces=[("192.168.110.1", "iot", 110)],
        pending_router_ips=["192.168.120.1"],
        unknown_hosts=[("192.168.100.60", None), ("192.168.100.61", None), ("192.168.100.142", None),
                       ("192.168.110.30", "Espressif Inc."), ("192.168.110.31", "Espressif Inc.")],
        outages={"AP Obergeschoss": [range(200, 204)]},
        down_events=[("Grafana", "Service Grafana (3000) is down", 25)],
        patches={d[0]: (7, 2) for d in devices if d[6] and d[6][3] == "0.3.4"},
        reboot_required={"Unraid"},
        link_colors={"10GbE": "#dfe6ee", "2.5GbE": "#3db8f5", "1GbE": "#a6e35b", "WLAN": "#2ec4a6"},
    )


# ------------------------------------------------------------------------------------------ company

_DEBIAN = "Debian GNU/Linux 12 (bookworm)"
_UBUNTU = "Ubuntu 24.04.1 LTS"
_PVE = "Debian GNU/Linux 12 (bookworm) · Proxmox VE 8.2"
_WEB = [("Web UI", "https", 443, True)]
_SSH = ("SSH", "ssh", 22, True)

_FLOORS = {
    "EG": ("Access EG", ["AP EG Empfang", "AP EG Besprechung"]),
    "OG1": ("Access OG1", ["AP OG1 Ost", "AP OG1 West"]),
    "OG2": ("Access OG2", ["AP OG2 Ost", "AP OG2 West"]),
    "Lager": ("Access Lager", ["AP Lager Halle", "AP Lager Außen"]),
    "Werkstatt": ("Access Werkstatt", ["AP Werkstatt"]),
}


def _mac(n: int) -> str:
    return f"02:47:4c:{(n >> 16) & 255:02x}:{(n >> 8) & 255:02x}:{n & 255:02x}"


def _vm(parent: str, **extra) -> dict:
    return {"virtual_type": "vm", "parent": parent, **extra}


def _ct(parent: str, **extra) -> dict:
    return {"virtual_type": "docker", "parent": parent, **extra}


class _CompanyBuilder:
    """Builder that structures the generation of the company demo scenario."""

    def __init__(self) -> None:
        self.devices: list[tuple] = []
        self.links: list[tuple] = []
        self.interfaces: list[tuple[str, str, str, int | None, str]] = []

    def add(self, spec: DeviceSpec) -> None:
        self.devices.append(spec.to_row())

    def link(self, a: str, b: str, kind: str, role: str = "primary") -> None:
        self.links.append((a, b, kind) if role == "primary" else (a, b, kind, role))

    def build_core(self) -> None:
        """Core network: firewall, core, aggregation and access switches, APs, UPS (VLAN 10)."""
        self.add(DeviceSpec("fw-01", "10.20.10.1", "firewall", "Firewalls",
                            flags={"subtype": "nftables / keepalived", "vendor": "Supermicro", "max_ports": 8},
                            services=[_SSH, ("Web UI", "https", 443, True)], profile=(_DEBIAN, 16, 14, CURRENT_AGENT)))
        for name, ip in (("Core-Switch 01", "10.20.10.2"), ("Core-Switch 02", "10.20.10.3")):
            self.add(DeviceSpec(name, ip, "switch", "Netzwerk",
                                flags={"subtype": "Core (Stack)", "vendor": "Juniper", "max_ports": 48},
                                services=[_SSH, *_WEB]))
        self.link("fw-01", "Core-Switch 01", "Fiber")
        self.link("Core-Switch 01", "Core-Switch 02", "Fiber")

        aggregation = {
            "Agg Serverraum": ("10.20.10.5", "Core-Switch 01"),
            "Agg Verwaltung": ("10.20.10.6", "Core-Switch 02"),
            "Agg Lager": ("10.20.10.7", "Core-Switch 02"),
        }
        for name, (ip, core) in aggregation.items():
            self.add(DeviceSpec(name, ip, "switch", "Netzwerk",
                                flags={"subtype": "Aggregation", "vendor": "Juniper", "max_ports": 24},
                                services=[_SSH, *_WEB]))
            self.link(core, name, "Fiber")

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
            self.add(DeviceSpec(
                name, ip, "switch", "Netzwerk",
                flags={"subtype": "Top of Rack" if tor else "Access PoE+",
                       "vendor": "Juniper" if tor else "Aruba", "max_ports": 48,
                       # Rack A's top-of-rack switch is down: nodes/TrueNAS fail over to rack B, UPS is cut off
                       "offline": name == "ToR Rack A"},
                services=[_SSH, *_WEB],
            ))
            self.link(uplink, name, kind)

        aps = {
            "AP EG Empfang": ("10.20.10.30", "Access EG"), "AP EG Besprechung": ("10.20.10.31", "Access EG"),
            "AP OG1 Ost": ("10.20.10.32", "Access OG1"), "AP OG1 West": ("10.20.10.33", "Access OG1"),
            "AP OG2 Ost": ("10.20.10.34", "Access OG2"), "AP OG2 West": ("10.20.10.35", "Access OG2"),
            "AP Lager Halle": ("10.20.10.36", "Access Lager"), "AP Lager Außen": ("10.20.10.37", "Access Lager"),
            "AP Werkstatt": ("10.20.10.38", "Access Werkstatt"),
        }
        for name, (ip, switch) in aps.items():
            self.add(DeviceSpec(name, ip, "webui", "Netzwerk",
                                flags={"is_ap": True, "subtype": "Access Point Wi-Fi 6E", "vendor": "Aruba"},
                                services=_WEB))
            self.link(switch, name, "2.5GbE")

        self.add(DeviceSpec("USV Serverraum", "10.20.10.50", "webui", "Netzwerk",
                            flags={"subtype": "USV (NUT)", "vendor": "APC"},
                            services=[("NUT", "nut", 3493, True), ("Web UI", "http", 80, True)]))
        self.link("ToR Rack A", "USV Serverraum", "1GbE")

    def build_proxmox(self) -> None:
        """Proxmox cluster, storage, and all guest VMs / containers."""
        nodes = {"pve-01": ("ToR Rack A", 41), "pve-02": ("ToR Rack A", 47), "pve-03": ("ToR Rack B", 55), "pve-04": ("ToR Rack B", 38)}
        for i, (name, (tor, cpu)) in enumerate(nodes.items(), start=1):
            ceph = [("Ceph Dashboard", "https", 8443, True)] if i == 1 else []
            self.add(DeviceSpec(
                name, f"10.20.20.1{i}", "server", "Server",
                flags={"is_host": True, "subtype": "Proxmox VE", "vendor": "Supermicro", "max_ports": 6},
                services=[("Proxmox", "https", 8006, True), _SSH, *ceph],
                profile=(_PVE, 256, cpu, CURRENT_AGENT),
            ))
            self.link(tor, name, "10GbE")
            self.interfaces.append((name, f"10.20.30.1{i}", "cluster", 30, "Corosync / Ceph"))
            self.interfaces.append((name, f"10.20.40.1{i}", "backup", 40, "Backup"))

        self.add(DeviceSpec("pbs-01", "10.20.40.20", "server", "Server",
                            flags={"subtype": "Proxmox Backup Server", "vendor": "Supermicro"},
                            services=[("Backup Server", "https", 8007, True), _SSH],
                            profile=(_DEBIAN, 64, 22, CURRENT_AGENT)))
        self.link("ToR Rack B", "pbs-01", "10GbE")
        self.interfaces.append(("pbs-01", "10.20.20.20", "server", 20, "Management"))

        self.add(DeviceSpec("TrueNAS", "10.20.20.30", "nas", "NAS / Storage",
                            flags={"subtype": "TrueNAS SCALE", "vendor": "iXsystems"},
                            services=[("Web UI", "https", 443, True), ("SMB", "smb", 445, True), ("NFS", "nfs", 2049, True), _SSH],
                            profile=("TrueNAS SCALE 24.10 (Debian 12)", 128, 31, CURRENT_AGENT)))
        self.link("ToR Rack A", "TrueNAS", "10GbE")
        self.interfaces.append(("TrueNAS", "10.20.40.30", "backup", 40, "Replikation"))

        self.add(DeviceSpec("Archiv-NAS", "10.20.40.31", "nas", "NAS / Storage",
                            flags={"subtype": "Synology RS1221+", "vendor": "Synology"},
                            services=[("DSM", "https", 5001, True), ("Hyper Backup", "https", 6281, True)],
                            profile=("Synology DSM 7.2.2 (Linux 4.4)", 32, 17, "0.3.9")))
        self.link("ToR Rack B", "Archiv-NAS", "10GbE")

        # Guests on the nodes: VMs and containers
        self.add(DeviceSpec("dc-01", "10.20.20.101", "server", "Server", flags=_vm("pve-01", subtype="Samba AD DC"),
                            services=[("LDAP", "ldap", 389, True), ("Kerberos", "kerberos", 88, True), _SSH],
                            profile=(_UBUNTU, 8, 12, CURRENT_AGENT)))
        self.add(DeviceSpec("dns-01", "10.20.20.102", "server", "Server", flags=_vm("pve-01", subtype="Bind9"),
                            services=[("DNS", "dns", 53, True), _SSH], profile=(_DEBIAN, 2, 6, CURRENT_AGENT)))
        self.add(DeviceSpec("gitlab", "10.20.20.103", "webui", "Web Interfaces", flags=_vm("pve-01", subtype="GitLab CE"),
                            services=[("GitLab", "https", 443, True), _SSH], profile=(_UBUNTU, 16, 46, CURRENT_AGENT)))
        self.add(DeviceSpec("mail-gw", "10.20.90.10", "webui", "DMZ", flags=_vm("pve-01", subtype="Mailcow"),
                            services=[("SMTP", "smtp", 25, True), ("Webmail", "https", 443, True)]))
        self.add(DeviceSpec("nextcloud", "10.20.20.111", "webui", "Web Interfaces", flags=_vm("pve-02", subtype="Nextcloud Hub"),
                            services=[("Nextcloud", "https", 443, True), _SSH], profile=(_DEBIAN, 16, 28, CURRENT_AGENT)))
        self.add(DeviceSpec("postgres-01", "10.20.20.112", "server", "Server", flags=_vm("pve-02", subtype="PostgreSQL 16"),
                            services=[("PostgreSQL", "postgres", 5432, True), _SSH], profile=(_DEBIAN, 32, 37, CURRENT_AGENT)))
        self.add(DeviceSpec("erp", "10.20.20.113", "webui", "Web Interfaces", flags=_vm("pve-02", subtype="Odoo 17"),
                            services=[("Odoo", "http", 8069, False), _SSH]))
        self.add(DeviceSpec("web-01", "10.20.90.12", "webui", "DMZ", flags=_vm("pve-02", subtype="Nginx"),
                            services=[("HTTPS", "https", 443, True)]))
        self.add(DeviceSpec("docker-01", "10.20.20.120", "server", "Server", flags=_vm("pve-03", subtype="Docker Host"),
                            services=[("Portainer", "https", 9443, True), _SSH], profile=(_DEBIAN, 32, 63, CURRENT_AGENT)))
        self.add(DeviceSpec("monitoring", "10.20.20.121", "webui", "Web Interfaces", flags=_vm("pve-03", subtype="Zabbix 7"),
                            services=[("Zabbix", "https", 443, True), _SSH], profile=(_UBUNTU, 8, 33, CURRENT_AGENT)))
        for i, role in enumerate(("master", "worker-1", "worker-2"), start=1):
            self.add(DeviceSpec(f"k3s-{role}", f"10.20.20.13{i}", "server", "Server", flags=_vm("pve-03", subtype="k3s"),
                                services=[("Kubernetes API", "https", 6443, True), _SSH],
                                profile=(_DEBIAN, 16, 44 + 6 * i, CURRENT_AGENT)))
        self.add(DeviceSpec("jumphost", "10.20.20.143", "server", "Server", flags=_vm("pve-04", subtype="Bastion"),
                            services=[_SSH], profile=(_DEBIAN, 2, 4, CURRENT_AGENT)))
        self.add(DeviceSpec("iot-gw", "10.20.60.10", "webui", "IoT", flags=_vm("pve-04", subtype="Home Assistant OS"),
                            services=[("Home Assistant", "http", 8123, True)]))
        self.add(DeviceSpec("frigate", "10.20.60.12", "webui", "IoT", flags=_vm("pve-04", subtype="Frigate NVR"),
                            services=[("Frigate", "http", 5000, True)]))
        self.add(DeviceSpec("mqtt", "10.20.60.11", "webui", "IoT", flags=_ct("pve-04", subtype="Mosquitto (LXC)"),
                            services=[("MQTT", "mqtt", 1883, True)]))
        self.add(DeviceSpec("netbox", "10.20.20.141", "webui", "Web Interfaces", flags=_ct("pve-04", subtype="NetBox (LXC)"),
                            services=[("NetBox", "https", 443, True)]))
        for name, ip, svc, port, up in (("grafana", "10.20.20.122", "Grafana", 3000, True),
                                        ("uptime-kuma", "10.20.20.123", "Uptime Kuma", 3001, True),
                                        ("vaultwarden", "10.20.20.142", "Vaultwarden", 443, True),
                                        ("wiki", "10.20.20.114", "BookStack", 6875, True)):
            self.add(DeviceSpec(name, ip, "webui", "Web Interfaces", flags=_ct("docker-01"),
                                services=[(svc, "https" if port == 443 else "http", port, up)]))
        self.add(DeviceSpec("traefik", "10.20.90.11", "webui", "DMZ", flags=_ct("docker-01", subtype="Reverse Proxy"),
                            services=[("Dashboard", "http", 8080, True), ("HTTPS", "https", 443, True)]))

    def build_offices(self) -> None:
        """Wired workstations, printers, and mobile devices across floors."""
        desks = [("empfang", "EG", 1), ("gf", "OG2", 1), ("buchhaltung", "OG1", 3), ("vertrieb", "OG1", 4),
                 ("entwicklung", "OG2", 6), ("lager", "Lager", 2), ("werkstatt", "Werkstatt", 2)]
        host = 20
        for dept, floor, count in desks:
            for n in range(1, count + 1):
                host += 1
                name = f"ws-{dept}-{n:02d}"
                agent = (("Fedora Linux 40 (Workstation)", 32, 24 + 7 * n, CURRENT_AGENT) if dept == "entwicklung" and n <= 3 else None)
                self.add(DeviceSpec(name, f"10.20.50.{host}", "unknown", "Clients",
                                    flags={"subtype": "Linux Workstation", "vendor": "Lenovo"},
                                    services=[_SSH] if agent else [], profile=agent))
                self.link(_FLOORS[floor][0], name, "1GbE")

        printers = [("Drucker EG", "EG", "Brother"), ("Drucker OG1", "OG1", "Kyocera"), ("Farbdrucker OG2", "OG2", "HP"),
                    ("Plotter Werkstatt", "Werkstatt", "Canon"), ("Etikettendrucker Lager", "Lager", "Zebra")]
        for i, (name, floor, vendor) in enumerate(printers):
            self.add(DeviceSpec(name, f"10.20.50.{200 + i}", "webui", "Drucker",
                                flags={"subtype": "Drucker", "vendor": vendor, "offline": name == "Plotter Werkstatt"},
                                services=[("IPP", "ipp", 631, True), ("Web UI", "http", 80, True)]))
            self.link(_FLOORS[floor][0], name, "1GbE")

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
            self.add(DeviceSpec(name, f"10.20.50.{100 + i}", "unknown", "Clients", flags=flags))
            ap_list = _FLOORS[floor][1]
            self.link(ap_list[i % len(ap_list)], name, "WLAN")

    def build_iot(self) -> None:
        """IoT devices: Shellys, PoE cameras, access control, and weather station."""
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
            self.add(DeviceSpec(name, f"10.20.60.{50 + i}", "webui", "IoT", flags=flags, services=[("Web UI", "http", 80, not flags["offline"])]))
            if wired:
                self.link(_FLOORS[floor][0], name, "1GbE")
            else:
                ap_list = _FLOORS[floor][1]
                self.link(ap_list[i % len(ap_list)], name, "WLAN")

        cameras = [("Kamera Eingang", "EG"), ("Kamera Parkplatz", "Lager"), ("Kamera Lager Tor", "Lager"), ("Kamera Halle", "Lager"), ("Kamera Werkstatt", "Werkstatt")]
        for i, (name, floor) in enumerate(cameras):
            self.add(DeviceSpec(name, f"10.20.60.{20 + i}", "webui", "IoT",
                                flags={"subtype": "IP-Kamera (PoE)", "vendor": "Reolink", "offline": name == "Kamera Parkplatz"},
                                services=[("RTSP", "rtsp", 554, True), ("Web UI", "http", 80, True)]))
            self.link(_FLOORS[floor][0], name, "1GbE")
        self.add(DeviceSpec("Zutrittskontrolle", "10.20.60.30", "webui", "IoT", flags={"subtype": "Türcontroller", "vendor": "Siemens"}, services=_WEB))
        self.link("Access EG", "Zutrittskontrolle", "1GbE")
        self.add(DeviceSpec("Wetterstation Dach", "10.20.60.31", "webui", "IoT", flags={"subtype": "Wetterstation", "vendor": "Ecowitt", "is_wlan": True}, services=[("Web UI", "http", 80, True)]))
        self.link("AP Lager Außen", "Wetterstation Dach", "WLAN")

    def build_redundancy(self) -> None:
        """Standby paths taking over on primary failure (Agg Lager stays deliberate single point of failure)."""
        self.link("fw-01", "Core-Switch 02", "Fiber", "backup")
        self.link("Core-Switch 01", "Agg Verwaltung", "Fiber", "backup")
        self.link("Core-Switch 02", "Agg Serverraum", "Fiber", "backup")
        for node, tor in (("pve-01", "ToR Rack B"), ("pve-02", "ToR Rack B"), ("pve-03", "ToR Rack A"), ("pve-04", "ToR Rack A")):
            self.link(tor, node, "10GbE", "backup")
        self.link("ToR Rack B", "TrueNAS", "10GbE", "backup")

    def build_guests(self) -> None:
        """Guest Wi-Fi devices (VLAN 70)."""
        guests = [("Gast iPhone", "AP EG Besprechung"), ("Gast Laptop 1", "AP EG Besprechung"), ("Gast Laptop 2", "AP EG Besprechung"),
                  ("Gast Android", "AP EG Empfang"), ("Gast iPad", "AP EG Empfang"), ("Lieferant Scanner", "AP Lager Halle")]
        for i, (name, ap) in enumerate(guests):
            self.add(DeviceSpec(name, f"10.20.70.{100 + i}", "unknown", "Gäste", flags={"is_wlan": True, "subtype": "Gastgerät", "offline": name == "Gast Laptop 2"}))
            self.link(ap, name, "WLAN")

    def finish(self) -> Scenario:
        """Assign MAC addresses and assemble the completed Scenario."""
        for i, d in enumerate(self.devices):
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
        routed = {"server", "backup", "clients", "iot", "dmz"}

        return Scenario(
            name="company",
            domain="musterfirma.lan",
            devices=self.devices,
            links=self.links,
            subnets=[(key, f"10.20.{vlan}.0/24", label, vlan, f"10.20.{vlan}.1" if key != "cluster" else None) for key, vlan, label in vlans],
            extra_groups=[("Netzwerk", "network", 1), ("DMZ", "shield", 4), ("Drucker", "printer", 5), ("IoT", "home", 6),
                          ("Clients", "laptop", 7), ("Gäste", "users", 8)],
            racks=[("Serverraum Rack A", 42), ("Serverraum Rack B", 42), ("Netzwerkschrank Verwaltung", 24), ("Verteiler Lager", 12)],
            rack_slots=rack_slots,
            grid=tree_grid(self.devices, self.links, root="fw-01"),
            router="fw-01",
            router_mac="02:47:4c:00:00:01",
            router_interfaces=[(f"10.20.{vlan}.1", key, vlan) for key, vlan, _ in vlans if key in routed],
            pending_router_ips=["10.20.70.1"],
            interfaces=self.interfaces,
            unknown_hosts=[("10.20.60.240", "Espressif Inc."), ("10.20.60.241", "Espressif Inc."), ("10.20.60.242", "Tuya Smart"),
                           ("10.20.50.230", None), ("10.20.70.150", "Apple, Inc."), ("10.20.70.151", None)],
            outages={"AP Lager Außen": [range(150, 152), range(205, 208), range(270, 271)], "Access Werkstatt": [range(96, 98)]},
            down_events=[("erp", "Service Odoo (8069) is down", 12)],
            patches={"pve-02": (12, 3), "Archiv-NAS": (5, 1), "ws-entwicklung-02": (23, 6), "gitlab": (4, 0), "pbs-01": (2, 0)},
            reboot_required={"pve-03", "ws-entwicklung-02"},
            link_colors={"Fiber": "#f5a524", "10GbE": "#dfe6ee", "2.5GbE": "#3db8f5", "1GbE": "#a6e35b", "WLAN": "#2ec4a6"},
            rack_items=[
                ("USV Netzwerkschrank", "Netzwerkschrank Verwaltung", "ups", 18, 2, 4, "Power"),
                ("Patchfeld Kupfer EG", "Netzwerkschrank Verwaltung", "patch_copper", 23, 1, 24, "RJ45"),
                ("Steckdosenleiste", "Netzwerkschrank Verwaltung", "power_strip", 16, 1, 8, "Power"),
                ("Blende", "Netzwerkschrank Verwaltung", "blank", 19, 1, 0, "RJ45"),
                ("Kabelführung", "Serverraum Rack A", "cable_management", 35, 1, 0, "RJ45"),
                ("Patchfeld Glasfaser", "Serverraum Rack B", "patch_fiber", 41, 1, 12, "LC"),
                ("Switch Lager (unmanaged)", "Verteiler Lager", "switch_unmanaged", 11, 1, 8, "RJ45"),
            ],
            port_counts={"ToR Rack A": (48, "RJ45"), "ToR Rack B": (48, "RJ45"), "Access EG": (48, "RJ45"), "Access OG1": (48, "RJ45"),
                         "pve-01": (4, "RJ45"), "pve-02": (4, "RJ45"), "pve-03": (4, "RJ45"), "pve-04": (4, "RJ45")},
            cables=[
                ("ToR Rack A", 1, "pve-01", 1, "DAC / Modul"),
                ("ToR Rack A", 2, "pve-02", 1, "DAC / Modul"),
                ("ToR Rack B", 3, "pve-03", 1, "DAC / Modul"),
                ("USV Netzwerkschrank", 1, "Steckdosenleiste", 1, "Stromkabel C13"),
                ("Patchfeld Kupfer EG", 1, "Access EG", 2, "Cat6"),
                ("Patchfeld Kupfer EG", 2, "Access OG1", 1, "Cat6"),
            ],
        )


def company() -> Scenario:
    builder = _CompanyBuilder()
    builder.build_core()
    builder.build_proxmox()
    builder.build_offices()
    builder.build_iot()
    builder.build_redundancy()
    builder.build_guests()
    return builder.finish()


def _build_tree_children(devices: list[tuple], links: list[tuple], root: str) -> dict[str, list[str]]:
    """Build directed child mapping from primary links and device parent links, starting at root."""
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
    return children


def tree_grid(devices: list[tuple], links: list[tuple], root: str) -> dict[str, tuple[float, float]]:
    """(column, row) per device for the React topology: a tidy tree from `root` over primary links, then guests under their host."""
    children = _build_tree_children(devices, links, root)
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
