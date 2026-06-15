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

    def list_issues(self) -> list:
        """Get the active list of issues (offline agents, down services) from summary.

        Returns:
            list: The list of active issues.
        """
        return self.client._request("GET", "/api/issues")
