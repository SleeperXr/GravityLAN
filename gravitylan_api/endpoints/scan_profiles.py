from .base import BaseEndpoint


class ScanProfilesEndpoint(BaseEndpoint):
    """API endpoints for scan profile management."""

    def list(self) -> list:
        """Get the list of predefined network scan profiles.

        Returns:
            list: The scan profiles list payload.
        """
        return self.client._request("GET", "/api/scan-profiles")
