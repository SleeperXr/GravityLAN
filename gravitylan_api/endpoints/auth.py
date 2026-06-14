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
