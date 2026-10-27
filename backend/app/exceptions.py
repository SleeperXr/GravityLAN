"""
Centralized exception handling for GravityLAN.
Provides the base error type and the specific errors raised by the API.
"""

from fastapi import status

class GravityLANError(Exception):
    """Base class for all GravityLAN exceptions."""
    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class DeviceNotFoundError(GravityLANError):
    """Raised when a device is not found in the database."""
    def __init__(self, device_id: int):
        super().__init__(
            message=f"Device with ID {device_id} not found",
            status_code=status.HTTP_404_NOT_FOUND
        )
