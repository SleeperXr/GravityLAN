from .base import BaseEndpoint


class TopologyEndpoint(BaseEndpoint):
    """API endpoints for network topology."""

    def map(self) -> dict:
        """Get the unified topology map (devices, links, racks).

        Returns:
            dict: The topology map payload.
        """
        return self.client._request("GET", "/api/topology/map")

    def nodes(self) -> list:
        """Get the flat list of nodes (devices) from the topology map.

        Returns:
            list: The list of device nodes.
        """
        return self.client._request("GET", "/api/topology/nodes")

    def edges(self) -> list:
        """Get the flat list of edges (links) from the topology map.

        Returns:
            list: The list of connection links.
        """
        return self.client._request("GET", "/api/topology/edges")
