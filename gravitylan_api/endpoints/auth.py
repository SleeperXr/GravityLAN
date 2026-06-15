from typing import Optional
from .base import BaseEndpoint


class AuthEndpoint(BaseEndpoint):
    """API endpoints for session authentication."""

    def login(self, password: str) -> dict:
        """Authenticate and establish a session.

        Args:
            password: The admin password.

        Returns:
            dict: The login response status.
        """
        payload = {"password": password}
        return self.client._request("POST", "/api/auth/login", json=payload)

    def logout(self) -> dict:
        """Log out and clear the active session.

        Returns:
            dict: The logout response status.
        """
        return self.client._request("POST", "/api/auth/logout")

    def check(self) -> dict:
        """Check if the current session/token is valid.

        Returns:
            dict: The check response status.
        """
        return self.client._request("POST", "/api/auth/check")

    def me(self) -> dict:
        """Perform token introspection to retrieve current scopes.

        Returns:
            dict: The active scopes configuration.
        """
        return self.client._request("GET", "/api/auth/me")

    def logs(self, limit: int = 50, level: Optional[str] = None) -> list:
        """Fetch system logs from the server log buffer.

        Args:
            limit: The maximum number of log lines to retrieve (default 50).
            level: The log level filter (e.g. INFO, ERROR).

        Returns:
            list: The list of parsed logs.
        """
        params = {"limit": limit}
        if level is not None:
            params["level"] = level
        return self.client._request("GET", "/api/logs", params=params)
