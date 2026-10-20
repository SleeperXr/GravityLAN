"""Import subnets/VLANs from a router: provider registry.

snmp works with most routers and firewalls (read-only SNMP); unifi uses the
official local API of UniFi consoles. See base.py for adding providers.
"""

from app.services.router_import.base import RouterImportError, RouterNetwork, RouterProvider
from app.services.router_import.snmp import SnmpProvider
from app.services.router_import.unifi import UnifiProvider

PROVIDERS: dict[str, type[RouterProvider]] = {
    SnmpProvider.key: SnmpProvider,
    UnifiProvider.key: UnifiProvider,
}

__all__ = ["PROVIDERS", "RouterImportError", "RouterNetwork", "RouterProvider"]
