"""
Centralized exception handling for GravityLAN.
Provides specific error types for API, database, and scanner operations.
"""

from fastapi import status

class GravityLANError(Exception):
    """Base class for all GravityLAN exceptions."""
    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class ScannerError(GravityLANError):
    """Base class for scanner-related failures."""
    def __init__(self, message: str, detail: str = ""):
        full_message = f"Scanner Error: {message}"
        if detail:
            full_message += f" ({detail})"
        super().__init__(
            message=full_message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )

class NetworkDiscoveryError(ScannerError):
    """Raised when network scanning or host discovery fails."""
    def __init__(self, subnet: str, reason: str):
        super().__init__(
            message=f"Failed to scan subnet {subnet}",
            detail=reason
        )

class DeviceNotFoundError(GravityLANError):
    """Raised when a device is not found in the database."""
    def __init__(self, device_id: int):
        super().__init__(
            message=f"Device with ID {device_id} not found",
            status_code=status.HTTP_404_NOT_FOUND
        )

class AgentNotFoundError(GravityLANError):
    """Raised when an agent operation is attempted on a device without an agent."""
    def __init__(self, device_id: int):
        super().__init__(
            message=f"No active agent found for device {device_id}",
            status_code=status.HTTP_404_NOT_FOUND
        )

class DatabaseOperationalError(GravityLANError):
    """Raised when a database operation fails."""
    def __init__(self, detail: str):
        super().__init__(
            message=f"Database error: {detail}",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )

class ConfigurationError(GravityLANError):
    """Raised when there is a system configuration issue."""
    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
        )
