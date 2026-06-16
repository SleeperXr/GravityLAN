import os
import time
import logging
from typing import Optional, Any, Dict
import requests

from .exceptions import (
    GravityLANError,
    GravityLANAuthError,
    GravityLANConnectionError,
    GravityLANHTTPError,
)
from .endpoints.agents import AgentsEndpoint
from .endpoints.devices import DevicesEndpoint
from .endpoints.topology import TopologyEndpoint
from .endpoints.network import NetworkEndpoint
from .endpoints.backup import BackupEndpoint
from .endpoints.auth import AuthEndpoint
from .endpoints.scan_profiles import ScanProfilesEndpoint
from .endpoints.health import HealthEndpoint

logger = logging.getLogger(__name__)


class GravityLANClient:
    """Synchronous client for the GravityLAN API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 10.0,
    ):
        """Initialize the GravityLAN API Client.

        Args:
            base_url: The root URL of the GravityLAN server (defaults to GRAVITYLAN_BASE_URL or http://localhost:8000).
            token: The Personal Access Token (PAT) (defaults to GRAVITYLAN_TOKEN).
            password: Optional admin password for session-based cookie login if token is not used.
            timeout: Request timeout in seconds (default 10s).
        """
        self.base_url = (
            base_url
            or os.environ.get("GRAVITYLAN_BASE_URL")
            or "http://localhost:8000"
        ).rstrip("/")
        
        self.token = token or os.environ.get("GRAVITYLAN_TOKEN")
        self.password = password or os.environ.get("GRAVITYLAN_PASSWORD")
        self.timeout = timeout

        # Set up requests session
        self.session = requests.Session()
        
        # Configure auth headers if token is present
        if self.token:
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})

        # Initialize endpoints
        self.agents = AgentsEndpoint(self)
        self.devices = DevicesEndpoint(self)
        self.topology = TopologyEndpoint(self)
        self.network = NetworkEndpoint(self)
        self.backup = BackupEndpoint(self)
        self.auth = AuthEndpoint(self)
        self.scan_profiles = ScanProfilesEndpoint(self)
        self.health = HealthEndpoint(self)


    def _ensure_login(self):
        """Log in via password authentication to establish a session cookie if needed."""
        if self.token:
            return  # No need for session cookies if using a token

        if not self.password:
            raise GravityLANAuthError(
                "Authentication required. Please provide a Personal Access Token (token) or password."
            )

        # Post password to login endpoint
        login_url = f"{self.base_url}/api/auth/login"
        try:
            logger.info("Attempting session login via password...")
            response = self.session.post(
                login_url,
                json={"password": self.password},
                timeout=self.timeout,
            )
            if response.status_code != 200:
                try:
                    detail = response.json().get("detail", response.reason)
                except Exception:
                    detail = response.reason
                raise GravityLANAuthError(f"Login failed: {detail}")
        except requests.exceptions.RequestException as e:
            raise GravityLANConnectionError(f"Failed to connect for login: {e}") from e

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Any] = None,
        **kwargs,
    ) -> Any:
        """Central request wrapper handling retries, auth refresh, and exceptions."""
        url = f"{self.base_url}{path}"
        
        # Exclude login/logout from auto-login checks to prevent infinite loops
        is_auth_route = path.startswith("/api/auth/login") or path.startswith("/api/auth/logout")

        # Verify session presence if using password and not an auth route
        if not self.token and not is_auth_route and not self.session.cookies.get("gravitylan_token"):
            self._ensure_login()

        for attempt in range(1, 4):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                    timeout=self.timeout,
                    **kwargs,
                )

                # If unauthorized on password auth, try to re-authenticate once
                if response.status_code == 401 and not self.token and not is_auth_route and attempt < 3:
                    logger.warning("Session unauthorized (401). Retrying authentication...")
                    self.session.cookies.clear()
                    self._ensure_login()
                    continue

                # Handle HTTP errors
                if not response.ok:
                    try:
                        error_detail = response.json().get("detail", response.reason)
                    except Exception:
                        error_detail = response.reason
                    raise GravityLANHTTPError(response.status_code, error_detail)

                # Return parsed JSON if content exists
                if response.status_code == 204 or not response.content:
                    return None
                try:
                    return response.json()
                except ValueError as e:
                    raise GravityLANError(f"Invalid JSON response from server: {e}")

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt == 3:
                    raise GravityLANConnectionError(
                        f"Request failed after 3 attempts due to connection/timeout: {e}"
                    ) from e
                
                # Exponential backoff: 2s, 4s
                backoff_time = 2**attempt
                logger.warning(
                    f"Connection failure on attempt {attempt}/3. Retrying in {backoff_time}s..."
                )
                time.sleep(backoff_time)
            except requests.exceptions.RequestException as e:
                # Catch other requests anomalies (e.g. TooManyRedirects)
                raise GravityLANError(f"API request encountered an error: {e}") from e
