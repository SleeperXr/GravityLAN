from typing import Any


class BaseEndpoint:
    """Base class for all resource-specific API endpoints.

    The client reference is intentionally untyped (``Any``) to keep this
    module free of imports from ``client.py`` — breaking the import cycle
    client -> endpoints -> client.
    """

    def __init__(self, client: Any):
        self.client = client
