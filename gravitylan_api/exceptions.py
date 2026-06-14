class GravityLANError(Exception):
    """Base exception class for GravityLAN API client errors."""
    pass


class GravityLANAuthError(GravityLANError):
    """Exception raised when authentication fails or is missing."""
    pass


class GravityLANConnectionError(GravityLANError):
    """Exception raised when network connections timeout or fail."""
    pass


class GravityLANHTTPError(GravityLANError):
    """Exception raised when API server returns a non-2xx status code.

    Attributes:
        status_code: The HTTP status code (e.g. 404, 500).
        message: The error message, usually from the server's detail field.
    """

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")
