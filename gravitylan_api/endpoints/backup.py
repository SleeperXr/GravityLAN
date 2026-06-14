from .base import BaseEndpoint


class BackupEndpoint(BaseEndpoint):
    """API endpoints for system backup/restore."""

    def export(self) -> dict:
        """Export the current database state as a dictionary.

        Returns:
            dict: The database backup export payload.
        """
        return self.client._request("GET", "/api/backup/export")
