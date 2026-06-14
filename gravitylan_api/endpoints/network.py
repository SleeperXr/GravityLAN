from typing import Optional, List
from .base import BaseEndpoint


class NetworkEndpoint(BaseEndpoint):
    """API endpoints for network and subnet configuration."""

    def list_subnets(self) -> List[dict]:
        """List all configured subnets.

        Returns:
            list[dict]: List of subnets.
        """
        return self.client._request("GET", "/api/network/subnets")

    def create_subnet(
        self,
        cidr: str,
        name: str,
        dns_server: Optional[str] = None,
        is_enabled: bool = True,
    ) -> dict:
        """Create a new subnet configuration.

        Args:
            cidr: Subnet in CIDR notation (e.g. 192.168.100.0/24).
            name: Human-readable name for the subnet.
            dns_server: Optional specific DNS server to use for this subnet.
            is_enabled: Whether scanning is enabled for this subnet.

        Returns:
            dict: The created subnet payload.
        """
        payload = {
            "cidr": cidr,
            "name": name,
            "dns_server": dns_server,
            "is_enabled": is_enabled,
        }
        return self.client._request("POST", "/api/network/subnets", json=payload)
