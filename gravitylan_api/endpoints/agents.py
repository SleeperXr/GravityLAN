from .base import BaseEndpoint


class AgentsEndpoint(BaseEndpoint):
    """API endpoints for agent management and overview."""

    def overview(self) -> dict:
        """Get an overview of all agents, including status, CPU, RAM, and uptime.

        Returns:
            dict: The agent overview payload.
        """
        return self.client._request("GET", "/api/agent/overview")

    def list(self) -> dict:
        """Get a list of all active agents with detailed system metrics.

        Returns:
            dict: The agent overview list payload.
        """
        return self.client._request("GET", "/api/agents")

    def get(self, device_id: int) -> dict:
        """Get the current status and latest metrics for a specific agent.

        Args:
            device_id (int): The ID of the monitored device.

        Returns:
            dict: The agent status and metrics payload.
        """
        return self.client._request("GET", f"/api/agents/{device_id}")

