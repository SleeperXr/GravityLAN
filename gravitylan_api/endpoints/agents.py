from .base import BaseEndpoint


class AgentsEndpoint(BaseEndpoint):
    """API endpoints for agent management and overview."""

    def overview(self) -> dict:
        """Get an overview of all agents, including status, CPU, RAM, and uptime.

        Returns:
            dict: The agent overview payload.
        """
        return self.client._request("GET", "/api/agent/overview")
