"""Device classification engine.

Classifies discovered network devices based on hostname patterns and open ports.
Ported from remote_access.py _classify_device() and _is_client_hostname().

The classifier determines device type (firewall, server, nas, webui) and
subtype (Sophos, Proxmox, Synology, etc.) using a priority-based rule system.
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set

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

# --- Service Templates Database ---

SERVICE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "ssh": {
        "name": "SSH",
        "protocol": "ssh",
        "port": 22,
        "color": "#34495e",
        "url_template": "ssh://{ip}",
    },
    "scp": {
        "name": "SCP",
        "protocol": "scp",
        "port": 22,
        "color": "#2c3e50",
        "url_template": "scp://{ip}",
    },
    "rdp": {
        "name": "RDP",
        "protocol": "rdp",
        "port": 3389,
        "color": "#2980b9",
        "url_template": "rdp://{ip}",
    },
    "http": {
        "name": "HTTP",
        "protocol": "http",
        "port": 80,
        "color": "#95a5a6",
        "url_template": "http://{ip}",
    },
    "https": {
        "name": "HTTPS",
        "protocol": "https",
        "port": 443,
        "color": "#7f8c8d",
        "url_template": "https://{ip}",
    },
    "smb": {
        "name": "SMB (File Share)",
        "protocol": "smb",
        "port": 445,
        "color": "#27ae60",
        "url_template": "smb://{ip}",
    },
    "sophos_admin": {
        "name": "Sophos WebAdmin",
        "protocol": "https",
        "port": 4444,
        "color": "#e67e22",
        "url_template": "https://{ip}:4444",
    },
    "sophos_vpn": {
        "name": "Sophos User Portal",
        "protocol": "https",
        "port": 443,
        "color": "#d35400",
        "url_template": "https://{ip}",
    },
    "securepoint": {
        "name": "Securepoint Admin",
        "protocol": "https",
        "port": 11115,
        "color": "#c0392b",
        "url_template": "https://{ip}:11115",
    },
    "proxmox": {
        "name": "Proxmox WebUI",
        "protocol": "https",
        "port": 8006,
        "color": "#d35400",
        "url_template": "https://{ip}:8006",
    },
    "esxi": {
        "name": "ESXi WebUI",
        "protocol": "https",
        "port": 443,
        "color": "#2980b9",
        "url_template": "https://{ip}",
    },
    "nutanix": {
        "name": "Nutanix Prism",
        "protocol": "https",
        "port": 9440,
        "color": "#2c3e50",
        "url_template": "https://{ip}:9440",
    },
    "synology": {
        "name": "DSM (HTTPS)",
        "protocol": "https",
        "port": 5001,
        "color": "#2980b9",
        "url_template": "https://{ip}:5001",
    },
    "synology_http": {
        "name": "DSM (HTTP)",
        "protocol": "http",
        "port": 5000,
        "color": "#3498db",
        "url_template": "http://{ip}:5000",
    },
    "qnap": {
        "name": "QTS WebUI",
        "protocol": "https",
        "port": 8080,
        "color": "#2980b9",
        "url_template": "https://{ip}:8080",
    },
    "homeassistant": {
        "name": "Home Assistant",
        "protocol": "http",
        "port": 8123,
        "color": "#3498db",
        "url_template": "http://{ip}:8123",
    },
    "iobroker": {
        "name": "ioBroker Admin",
        "protocol": "http",
        "port": 8081,
        "color": "#27ae60",
        "url_template": "http://{ip}:8081",
    },
    "cockpit": {
        "name": "Cockpit Admin",
        "protocol": "https",
        "port": 9090,
        "color": "#c0392b",
        "url_template": "https://{ip}:9090",
    },
    "webmin": {
        "name": "Webmin Admin",
        "protocol": "https",
        "port": 10000,
        "color": "#2980b9",
        "url_template": "https://{ip}:10000",
    },
}

# --- Helper Functions ---

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


def _refine_server_subtype(hostname: str, port_set: set[int]) -> str:
    """Determine a more specific server subtype from hostname keywords."""
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
    """Build a list of service dicts from open ports."""
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


class ClassificationRule(ABC):
    """Abstract base class for classification rules."""
    
    @abstractmethod
    def matches(self, hostname: str, port_set: Set[int]) -> bool:
        """Check if this rule applies to the device."""
        pass

    @abstractmethod
    def apply(self, host_info: Dict[str, Any], hostname: str, port_set: Set[int]) -> Dict[str, Any]:
        """Apply the classification logic and return updated host info."""
        pass

class FirewallRule(ClassificationRule):
    def matches(self, hostname: str, port_set: Set[int]) -> bool:
        if 4444 in port_set or 4445 in port_set: return True
        if 11115 in port_set: return True
        return any(p in hostname for p in FIREWALL_HOSTNAME_PATTERNS)

    def apply(self, host_info: Dict[str, Any], hostname: str, port_set: Set[int]) -> Dict[str, Any]:
        if 4444 in port_set or 4445 in port_set:
            return {**host_info, "device_type": "firewall", "device_subtype": "Sophos", "services": _build_services(port_set, firewall_type="sophos")}
        if 11115 in port_set:
            return {**host_info, "device_type": "firewall", "device_subtype": "Securepoint", "services": _build_services(port_set, firewall_type="securepoint")}
        return {**host_info, "device_type": "firewall", "device_subtype": "Router/Firewall", "services": _build_services(port_set)}

class HypervisorRule(ClassificationRule):
    def matches(self, hostname: str, port_set: Set[int]) -> bool:
        if 8006 in port_set: return True
        if 902 in port_set: return True
        if 9440 in port_set: return True
        # Only match by name if very specific
        h = hostname.upper()
        if "PROXMOX" in h or h.startswith("PVE-"): return True
        return any(kw in h for kw in ["ESXI", "VCENTER", "HYPER-V", "XEN"])

    def apply(self, host_info: Dict[str, Any], hostname: str, port_set: Set[int]) -> Dict[str, Any]:
        if 8006 in port_set or "PVE" in hostname:
            return {**host_info, "device_type": "server", "device_subtype": "Proxmox", "services": _build_services(port_set, add_specific=["proxmox"])}
        if 902 in port_set:
            return {**host_info, "device_type": "server", "device_subtype": "ESXi", "services": _build_services(port_set, add_specific=["esxi"])}
        if 9440 in port_set:
            return {**host_info, "device_type": "server", "device_subtype": "Nutanix", "services": _build_services(port_set, add_specific=["nutanix"])}
        return {**host_info, "device_type": "server", "device_subtype": "Hypervisor", "services": _build_services(port_set)}

class NasRule(ClassificationRule):
    def matches(self, hostname: str, port_set: Set[int]) -> bool:
        is_synology_port = bool(port_set & {5000, 5001})
        is_nas_name = any(p in hostname for p in NAS_SYNOLOGY_PATTERNS) or any(p in hostname for p in NAS_QNAP_PATTERNS)
        return is_synology_port or is_nas_name

    def apply(self, host_info: Dict[str, Any], hostname: str, port_set: Set[int]) -> Dict[str, Any]:
        is_synology_port = bool(port_set & {5000, 5001})
        has_file_services = bool(port_set & {445, 2049})
        is_synology_name = any(p in hostname for p in NAS_SYNOLOGY_PATTERNS)
        
        if (is_synology_port and has_file_services) or (is_synology_port and is_synology_name):
            specific = ["synology" if 5001 in port_set else "synology_http"]
            return {**host_info, "device_type": "server", "device_subtype": "Synology", "services": _build_services(port_set, add_specific=specific)}
        
        if any(p in hostname for p in NAS_QNAP_PATTERNS) and port_set & {80, 443, 8080}:
            return {**host_info, "device_type": "server", "device_subtype": "QNAP", "services": _build_services(port_set, add_specific=["qnap"])}
        
        return {**host_info, "device_type": "server", "device_subtype": "NAS", "services": _build_services(port_set)}

class IotRule(ClassificationRule):
    def matches(self, hostname: str, port_set: Set[int]) -> bool:
        return bool(port_set & {8123, 8081})

    def apply(self, host_info: Dict[str, Any], hostname: str, port_set: Set[int]) -> Dict[str, Any]:
        if 8123 in port_set:
            return {**host_info, "device_type": "server", "device_subtype": "Home Assistant", "services": _build_services(port_set, add_specific=["homeassistant"])}
        return {**host_info, "device_type": "server", "device_subtype": "ioBroker", "services": _build_services(port_set, add_specific=["iobroker"])}

class ServerRule(ClassificationRule):
    def matches(self, hostname: str, port_set: Set[int]) -> bool:
        return any(kw in hostname for kw in SERVER_HOSTNAME_PATTERNS)

    def apply(self, host_info: Dict[str, Any], hostname: str, port_set: Set[int]) -> Dict[str, Any]:
        return {**host_info, "device_type": "server", "device_subtype": _refine_server_subtype(hostname, port_set), "services": _build_services(port_set)}

class GenericAdminRule(ClassificationRule):
    def matches(self, hostname: str, port_set: Set[int]) -> bool:
        return bool(port_set & {22, 3389, 80, 443, 8080, 8443})

    def apply(self, host_info: Dict[str, Any], hostname: str, port_set: Set[int]) -> Dict[str, Any]:
        # If it has any web port, classify as webui
        if port_set & {80, 443, 8080, 8443}:
            return {**host_info, "device_type": "webui", "device_subtype": "Web Interface", "services": _build_services(port_set)}
        
        # Otherwise (SSH/RDP only), it's a server/host
        device_subtype = "SSH Device" if 22 in port_set else "RDP Device"
        return {**host_info, "device_type": "server", "device_subtype": device_subtype, "services": _build_services(port_set)}

# Registered Rules in priority order
CLASSIFICATION_RULES: List[ClassificationRule] = [
    FirewallRule(),
    HypervisorRule(),
    NasRule(),
    IotRule(),
    ServerRule(),
    GenericAdminRule()
]

def classify_device(host_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Classify a network device using the modular rule engine."""
    hostname = (host_info.get("hostname") or "").upper()
    ports = host_info.get("ports", [])
    port_set = set(ports)

    # Base state
    result = {
        **host_info,
        "device_type": "unknown",
        "device_subtype": "Unknown",
        "services": [],
    }

    # Iterate through rules by priority
    for rule in CLASSIFICATION_RULES:
        if rule.matches(hostname, port_set):
            return rule.apply(result, hostname, port_set)

    # Filter out boring clients without admin interfaces
    if is_client_hostname(hostname) and not port_set:
        return None

    # Even if no rule matched, if we have any ports, return them as unknown device
    if port_set:
        result["services"] = _build_services(port_set)
        return result

    return result



