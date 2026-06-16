from typing import Optional, List
from .base import BaseEndpoint


class DevicesEndpoint(BaseEndpoint):
    """API endpoints for network device management."""

    def list(
        self, include_hidden: bool = False, group_id: Optional[int] = None
    ) -> List[dict]:
        """List all discovered devices, optionally filtering by visibility and group.

        Args:
            include_hidden: Whether to include devices hidden from the dashboard.
            group_id: Filter devices by group ID.

        Returns:
            list[dict]: List of devices.
        """
        params = {"include_hidden": str(include_hidden).lower()}
        if group_id is not None:
            params["group_id"] = str(group_id)

        return self.client._request("GET", "/api/devices", params=params)

    def get(self, device_id: int) -> dict:
        """Get details for a single device by ID.

        Args:
            device_id: The ID of the device.

        Returns:
            dict: The device details.
        """
        return self.client._request("GET", f"/api/devices/{device_id}")

    def refresh_info(self, device_id: int) -> dict:
        """Trigger a manual metadata refresh (Hostname, MAC, Vendor) for a device.

        Args:
            device_id: The ID of the device.

        Returns:
            dict: The updated device details.
        """
        return self.client._request("POST", f"/api/devices/{device_id}/refresh-info")

    def get_group(self, group_id: int) -> dict:
        """Get details for a single device group including its devices.

        Args:
            group_id: The ID of the group.

        Returns:
            dict: The group details and devices list.
        """
        return self.client._request("GET", f"/api/groups/{group_id}")

    def list_issues(
        self, device_id: Optional[int] = None, type: Optional[str] = None
    ) -> list:
        """Get the active list of issues (offline agents, down services) from summary.

        Args:
            device_id: Optional filter for a specific device by ID.
            type: Optional filter for issue type (e.g. "agent_offline").

        Returns:
            list: The list of active issues.
        """
        params = {}
        if device_id is not None:
            params["device_id"] = str(device_id)
        if type is not None:
            params["type"] = type

        return self.client._request("GET", "/api/issues", params=params)

    def list_notifications(
        self, since: Optional[str] = None, unread: Optional[bool] = None, device_id: Optional[int] = None
    ) -> list:
        """Get the dynamic feed of recent system notifications.

        Args:
            since: Optional ISO-8601 timestamp string filter.
            unread: Optional read status filter.
            device_id: Optional device ID filter.

        Returns:
            list: The list of notifications.
        """
        params = {}
        if since is not None:
            params["since"] = since
        if unread is not None:
            params["unread"] = str(unread).lower()
        if device_id is not None:
            params["device_id"] = str(device_id)

        return self.client._request("GET", "/api/notifications", params=params)

