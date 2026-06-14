from .base import BaseEndpoint


class TopologyEndpoint(BaseEndpoint):
    """API endpoints for network topology."""

    def map(self) -> dict:
        """Get the unified topology map (devices, links, racks).

        Returns:
            dict: The topology map payload.
        """
        return self.client._request("GET", "/api/topology/map")
