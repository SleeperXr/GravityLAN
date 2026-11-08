"""The stored form of what each DNS server answered for a device."""

import json
from typing import Any


def stored_dns_answers(raw: str | None) -> dict[str, Any] | None:
    """The JSON object in ``Device.dns_names``, None when it is empty or unreadable.

    It holds ``{"1": name, "2": name}`` plus ``"<n>_reason"`` for a server that gave no name.
    Values are not checked: a hand-edited backup can hold anything, so each reader keeps what it can use.
    """
    if not raw:
        return None
    try:
        stored = json.loads(raw)
    except ValueError:
        return None
    return stored if isinstance(stored, dict) else None
