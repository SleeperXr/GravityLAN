from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import GravityLANClient


class BaseEndpoint:
    """Base class for all resource-specific API endpoints."""

    def __init__(self, client: "GravityLANClient"):
        self.client = client
