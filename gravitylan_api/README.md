# gravitylan-api

Python client for the [GravityLAN](https://github.com/SleeperXr/GravityLAN) REST API. Only dependency: `requests`.

## Install

From a GravityLAN checkout:

```bash
pip install ./gravitylan_api
```

## Usage

```python
from gravitylan_api import GravityLANClient

client = GravityLANClient(base_url="http://gravitylan.local:8000", token="<API token>")

for device in client.devices.list():
    print(device["display_name"], device["ip"])

print(client.health.summary())
```

Authentication, in order of preference:

- **API token** (`token=` or `GRAVITYLAN_TOKEN`) — create one in the GravityLAN UI under *Settings → API Tokens*. Tokens are read-only by default.
- **Admin password** (`password=` or `GRAVITYLAN_PASSWORD`) — the client logs in, keeps the session cookie and re-authenticates once if the session expires.

`base_url` falls back to `GRAVITYLAN_BASE_URL`, then `http://localhost:8000`.

Endpoint groups: `client.devices`, `client.agents`, `client.network`, `client.topology`, `client.backup`, `client.scan_profiles`, `client.health`, `client.auth`.

Errors raise `GravityLANAuthError`, `GravityLANConnectionError` or `GravityLANHTTPError` (all subclasses of `GravityLANError`).

## Tests

From the repository root:

```bash
python -m pytest gravitylan_api/tests
```
