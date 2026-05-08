"""Device classification engine.

Classifies discovered network devices based on hostname patterns and open ports.
Ported from remote_access.py _classify_device() and _is_client_hostname().

The classifier determines device type (firewall, server, nas, webui) and
subtype (Sophos, Proxmox, Synology, etc.) using a priority-based rule system.
"""

import logging
import re

logger = logging.getLogger(__name__)

# --- Hostname Pattern Databases ---

FIREWALL_HOSTNAME_PATTERNS: list[str] = [
    "FIREWALL", "GATEWAY", "FW-", "-FW", "UTM", "ROUTER",
    "UDM", "USG", "UNIFI", "EDGEROUTER", "MOCA",
    "SPEEDPORT", "DIGIBOX", "EASYBOX", "HOMEBOX",
    "FRITZ", "FRITZBOX", "ZYXEL", "NETGEAR", "ASUS-RT", "TPLINK", "LINKSYS",
    "SOPHOS", "SECUREPOINT", "LANCOM", "BINTEC", "DRAYTEK",
    "FORTINET", "FORTIGATE", "WATCHGUARD", "BARRACUDA",
    "PALOALTO", "CHECKPOINT", "SONICWALL", "CISCO-ASA", "MERAKI",
    "OPNSENSE", "PFSENSE", "IPFIRE", "UNTANGLE",
    "MIKROTIK", "ROUTEROS",
]

HYPERVISOR_HOSTNAME_PATTERNS: list[str] = [
    "PVE", "PROXMOX", "ESXI", "VCENTER", "HYPER-V", "XEN",
]

NAS_SYNOLOGY_PATTERNS: list[str] = [
    "NAS", "DS-", "RS-", "SYNOLOGY", "DISKSTATION", "RACKSTATION",
]

NAS_QNAP_PATTERNS: list[str] = [
    "QNAP", "TS-", "TVS-",
]

SERVER_HOSTNAME_PATTERNS: list[str] = [
    # Infrastructure
    "SRV", "SERVER", "DC", "AD", "DNS", "DHCP", "WSUS", "SCCM", "WDS",
    "CLU", "NODE", "CLUSTER", "KMS", "CA", "PKI",
    # Terminal Services
    "TS", "TERM", "RDS", "VDI", "CITRIX", "CTX", "XEN", "VBOX",
    # Applications / Databases
    "APP", "ERP", "CRM", "SQL", "DB", "ORA", "MYSQL", "MARIA", "POSTGRE",
    "SAP", "BI", "DEV", "TEST", "PROD", "STAGE", "INT",
    # File / Print / Mail
    "FILE", "FS", "PRINT", "PRT", "MAIL", "EXCHANGE", "SMTP", "IMAP", "POP",
    # Web / Proxy
    "WEB", "WWW", "IIS", "APACHE", "NGINX", "PROXY", "PRX", "LB", "GW",
    # Virtualization / Management
    "HV", "VM-", "MGMT", "ADMIN", "MONITOR", "MON",
    "ZABBIX", "PRTG", "CHECKMK",
    "BACKUP", "VEEAM", "BCK",
    "NAS", "SAN", "STORAGE", "DOCKER", "KUBE",
    "VCENTER", "VCSA", "ESXI", "PVE", "PROXMOX",
    # Communication
    "PHONE", "PBX", "SIP", "VOIP", "UCC", "LYNC", "SKYPE", "3CX", "STARFACE",
]

CLIENT_HOSTNAME_PATTERNS: list[str] = [
    "LAPTOP-", "DESKTOP-", "PC-", "CLIENT-", "WKS-", "WORKSTATION",
    "NB-", "NOTEBOOK", "SURFACE",
    "ALEXA", "ECHO", "SONOS", "CHROMECAST", "HOST.DOCKER",
    "KYO", "EPSON", "HP-", "CANON", "BROTHER", "PRINTER", "DRUCKER",
]

# --- Service Templates ---

SERVICE_TEMPLATES: dict[str, dict] = {
    "ssh":           {"name": "SSH",           "protocol": "ssh",   "port": 22,    "color": "#27ae60", "url_template": "ssh://{ip}"},
    "rdp":           {"name": "RDP",           "protocol": "rdp",   "port": 3389,  "color": "#2980b9", "url_template": "ms-rdp://full%20address=s:{ip}"},
    "http":          {"name": "HTTP",          "protocol": "http",  "port": 80,    "color": "#7f8c8d", "url_template": "http://{ip}"},
    "https":         {"name": "HTTPS",         "protocol": "https", "port": 443,   "color": "#3498db", "url_template": "https://{ip}"},
    "smb":           {"name": "SMB",           "protocol": "smb",   "port": 445,   "color": "#f39c12", "url_template": "smb://{ip}"},
    "scp":           {"name": "SCP",           "protocol": "scp",   "port": 22,    "color": "#8e44ad", "url_template": "scp://{ip}"},
    "sophos_admin":  {"name": "Sophos Admin",  "protocol": "https", "port": 4444,  "color": "#e67e22", "url_template": "https://{ip}:4444"},
    "sophos_vpn":    {"name": "Sophos VPN",    "protocol": "https", "port": 4445,  "color": "#d68910", "url_template": "https://{ip}:4445"},
    "securepoint":   {"name": "Securepoint",   "protocol": "https", "port": 11115, "color": "#c0392b", "url_template": "https://{ip}:11115"},
    "proxmox":       {"name": "Proxmox",       "protocol": "https", "port": 8006,  "color": "#e57000", "url_template": "https://{ip}:8006"},
    "esxi":          {"name": "ESXi",          "protocol": "https", "port": 443,   "color": "#607d8b", "url_template": "https://{ip}"},
    "synology":      {"name": "Synology",      "protocol": "https", "port": 5001,  "color": "#217346", "url_template": "https://{ip}:5001"},
    "synology_http": {"name": "Synology",      "protocol": "http",  "port": 5000,  "color": "#217346", "url_template": "http://{ip}:5000"},
    "qnap":          {"name": "QNAP",          "protocol": "https", "port": 443,   "color": "#005a9c", "url_template": "https://{ip}"},
    "nutanix":       {"name": "Nutanix",       "protocol": "https", "port": 9440,  "color": "#024DA1", "url_template": "https://{ip}:9440"},
    "cockpit":       {"name": "Cockpit",       "protocol": "https", "port": 9090,  "color": "#0066cc", "url_template": "https://{ip}:9090"},
    "webmin":        {"name": "Webmin",        "protocol": "https", "port": 10000, "color": "#336791", "url_template": "https://{ip}:10000"},
    "homeassistant": {"name": "Home Assistant", "protocol": "http",  "port": 8123,  "color": "#41BDF5", "url_template": "http://{ip}:8123"},
    "iobroker":      {"name": "ioBroker",      "protocol": "http",  "port": 8081,  "color": "#3399CC", "url_template": "http://{ip}:8081"},
}


def is_client_hostname(hostname: str) -> bool:
    """Check if a hostname belongs to a client device (desktop, printer, IoT).

    Args:
        hostname: The hostname to check (case-insensitive).

    Returns:
        True if the hostname matches known client patterns.
    """
    if not hostname:
        return False

    h = hostname.upper().split(".")[0]

    # Wortmann/Terra pattern: R + 3-8 digits
    if re.match(r"^R\d{3,8}$", h):
        return True

    # Lenovo SNR pattern: 8 alphanumeric chars with at least one digit
    if re.match(r"^[A-Z0-9]{8}$", h) and any(c.isdigit() for c in h):
        return True

    # Generic client patterns
    return any(p in h for p in CLIENT_HOSTNAME_PATTERNS)


def classify_device(host_info: dict) -> dict | None:
    """Classify a network device by hostname patterns and open ports.

    Priority order:
    1. Firewalls (port-based, then hostname-based)
    2. Hypervisors (specific management ports)
    3. NAS devices (port + hostname combo)
    4. Servers (hostname patterns)
    5. Web/SSH interfaces (catch-all for admin-capable devices)

    Args:
        host_info: Dict with 'ip', 'hostname' (optional), 'ports' (list[int]).

    Returns:
        Enriched dict with 'device_type', 'device_subtype', 'services' added,
        or None if the device should be filtered out.
    """
    hostname = (host_info.get("hostname") or "").upper()
    ip = host_info.get("ip", "")
    ports = host_info.get("ports", [])
    port_set = set(ports)

    result = {
        **host_info,
        "device_type": "unknown",
        "device_subtype": "Unknown",
        "services": [],
    }

    # === 1. FIREWALL DETECTION (highest priority) ===

    if 4444 in port_set or 4445 in port_set:
        result["device_type"] = "firewall"
        result["device_subtype"] = "Sophos"
        result["services"] = _build_services(port_set, firewall_type="sophos")
        return result

    if 11115 in port_set:
        result["device_type"] = "firewall"
        result["device_subtype"] = "Securepoint"
        result["services"] = _build_services(port_set, firewall_type="securepoint")
        return result

    if any(p in hostname for p in FIREWALL_HOSTNAME_PATTERNS):
        result["device_type"] = "firewall"
        result["device_subtype"] = "Router/Firewall"
        result["services"] = _build_services(port_set)
        return result

    # === 2. HYPERVISOR DETECTION ===

    if 8006 in port_set or "PVE" in hostname:
        result["device_type"] = "server"
        result["device_subtype"] = "Proxmox"
        result["services"] = _build_services(port_set, add_specific=["proxmox"])
        return result

    if 902 in port_set:
        result["device_type"] = "server"
        result["device_subtype"] = "ESXi"
        result["services"] = _build_services(port_set, add_specific=["esxi"])
        return result

    if 9440 in port_set:
        result["device_type"] = "server"
        result["device_subtype"] = "Nutanix"
        result["services"] = _build_services(port_set, add_specific=["nutanix"])
        return result

    if any(kw in hostname for kw in HYPERVISOR_HOSTNAME_PATTERNS):
        result["device_type"] = "server"
        result["device_subtype"] = "Hypervisor"
        result["services"] = _build_services(port_set)
        return result

    # === 3. NAS DETECTION ===

    is_synology_port = bool(port_set & {5000, 5001})
    has_file_services = bool(port_set & {445, 2049})
    is_nas_name = any(p in hostname for p in NAS_SYNOLOGY_PATTERNS)
    is_qnap_name = any(p in hostname for p in NAS_QNAP_PATTERNS)

    if (is_synology_port and has_file_services) or (is_synology_port and is_nas_name):
        result["device_type"] = "server"
        result["device_subtype"] = "Synology"
        specific = ["synology" if 5001 in port_set else "synology_http"]
        result["services"] = _build_services(port_set, add_specific=specific)
        return result

    if is_qnap_name and port_set & {80, 443, 8080}:
        result["device_type"] = "server"
        result["device_subtype"] = "QNAP"
        result["services"] = _build_services(port_set, add_specific=["qnap"])
        return result

    # === 3.5 SMART HOME DETECTION ===

    if 8123 in port_set:
        result["device_type"] = "server"
        result["device_subtype"] = "Home Assistant"
        result["services"] = _build_services(port_set, add_specific=["homeassistant"])
        return result

    if 8081 in port_set:
        result["device_type"] = "server"
        result["device_subtype"] = "ioBroker"
        result["services"] = _build_services(port_set, add_specific=["iobroker"])
        return result

    # === 4. SERVER DETECTION ===

    if any(kw in hostname for kw in SERVER_HOSTNAME_PATTERNS):
        result["device_type"] = "server"
        result["device_subtype"] = _refine_server_subtype(hostname, port_set)
        result["services"] = _build_services(port_set)
        return result

    # === 5. WEB/SSH INTERFACES (catch-all) ===

    has_admin_services = bool(port_set & {22, 80, 443, 8080, 8443})

    if is_client_hostname(hostname) and not has_admin_services:
        return None

    if has_admin_services:
        result["device_type"] = "webui"
        result["device_subtype"] = "SSH Device" if 22 in port_set else "Web Interface"
        result["services"] = _build_services(port_set)
        return result

    # Even if no admin services, if we have any ports, return them as unknown device
    if port_set:
        result["services"] = _build_services(port_set)
        return result

    return result


def _refine_server_subtype(hostname: str, port_set: set[int]) -> str:
    """Determine a more specific server subtype from hostname keywords.

    Args:
        hostname: Uppercased hostname.
        port_set: Set of open ports.

    Returns:
        Refined subtype string.
    """
    role_map = [
        (["DC", "AD"], "Domain Controller"),
        (["DNS"], "DNS Server"),
        (["SQL", "DB", "ORA"], "Database"),
        (["FILE", "FS", "NAS"], "File Server"),
        (["BACKUP", "VEEAM"], "Backup Server"),
        (["TS", "TERM", "RDS", "CTX", "CITRIX"], "Terminal Server"),
        (["PHONE", "PBX", "SIP", "VOIP", "3CX"], "Phone System"),
        (["WEB", "IIS", "APACHE", "NGINX"], "Web Server"),
        (["MON", "PRTG", "ZABBIX", "CHECKMK"], "Monitoring"),
    ]

    for keywords, subtype in role_map:
        if any(kw in hostname for kw in keywords):
            return subtype

    # Fallback by port
    if 3389 in port_set:
        return "Windows Server"
    if 22 in port_set:
        return "Linux Server"

    return "Server"


def _build_services(
    port_set: set[int],
    firewall_type: str | None = None,
    add_specific: list[str] | None = None,
) -> list[dict]:
    """Build a list of service dicts from open ports.

    Maps open ports to known service templates and returns
    a list of service definitions ready for database insertion.

    Args:
        port_set: Set of open ports.
        firewall_type: If set, adds firewall-specific services.
        add_specific: Additional specific service keys to include.

    Returns:
        List of service dicts with name, protocol, port, color, url_template.
    """
    services: list[dict] = []
    handled_ports: set[int] = set()

    # Add specific services first (higher priority)
    if add_specific:
        for key in add_specific:
            if key in SERVICE_TEMPLATES:
                tmpl = SERVICE_TEMPLATES[key]
                services.append({**tmpl, "is_auto_detected": True})
                handled_ports.add(tmpl["port"])

    # Add firewall-specific services
    if firewall_type == "sophos":
        for key in ("sophos_admin", "sophos_vpn"):
            tmpl = SERVICE_TEMPLATES[key]
            if tmpl["port"] in port_set:
                services.append({**tmpl, "is_auto_detected": True})
                handled_ports.add(tmpl["port"])
    elif firewall_type == "securepoint":
        tmpl = SERVICE_TEMPLATES["securepoint"]
        if tmpl["port"] in port_set:
            services.append({**tmpl, "is_auto_detected": True})
            handled_ports.add(tmpl["port"])

    # Standard service mapping
    standard_port_map = {
        22:   "ssh",
        3389: "rdp",
        445:  "smb",
        443:  "https",
        80:   "http",
        9090: "cockpit",
        10000: "webmin",
        8123: "homeassistant",
        8081: "iobroker",
    }

    for port, key in standard_port_map.items():
        if port in port_set and port not in handled_ports:
            services.append({**SERVICE_TEMPLATES[key], "is_auto_detected": True})
            handled_ports.add(port)

    # SCP if SSH available
    if 22 in port_set and "scp" not in [s.get("protocol") for s in services]:
        services.append({**SERVICE_TEMPLATES["scp"], "is_auto_detected": True})

    # Generic web ports
    generic_web_ports = [8080, 8443, 9443, 8000, 8008, 8888]
    for port in generic_web_ports:
        if port in port_set and port not in handled_ports:
            is_https = port in {8443, 9443}
            protocol = "https" if is_https else "http"
            services.append({
                "name": f"Port {port}",
                "protocol": protocol,
                "port": port,
                "color": "#34495e",
                "url_template": f"{protocol}://{{ip}}:{port}",
                "is_auto_detected": True,
            })

    # Final catch-all for any other port not yet handled
    for port in port_set:
        if port not in handled_ports:
            # Try to guess protocol (mostly TCP)
            services.append({
                "name": f"Port {port}",
                "protocol": "tcp",
                "port": port,
                "color": "#34495e",
                "url_template": f"http://{{ip}}:{port}",
                "is_auto_detected": True,
            })
            handled_ports.add(port)

    return services
