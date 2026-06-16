from .base import BaseEndpoint


class HealthEndpoint(BaseEndpoint):
    """API endpoints for system health aggregate overview."""

    def summary(self) -> dict:
        """Get the unified aggregate health summary of the network.

        Returns:
            dict: The system health summary data.
        """
        return self.client._request("GET", "/api/health/summary")
