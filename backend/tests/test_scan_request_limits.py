"""Scan requests are bounded like the subnet management (#43, GHSA-wc49-p8xv-hq2x)."""
import pytest
from pydantic import ValidationError

from app.scanner.subnets import scan_target_ips
from app.schemas.scan import MAX_SCAN_SUBNETS, ScanRequest

OVERSIZED = ["0.0.0.0/0", "10.0.0.0/8", "172.16.0.0/12", "::/0", "2001:db8::/32", "nonsense"]


@pytest.mark.parametrize("subnet", OVERSIZED)
def test_scan_request_rejects_oversized_or_invalid_subnets(subnet):
    with pytest.raises(ValidationError):
        ScanRequest(subnets=[subnet])


def test_scan_request_normalizes_and_caps_subnets():
    assert ScanRequest(subnets=["192.168.1.5/24", "192.168.1.0/24", "10.0.0.0/16"]).subnets == [
        "192.168.1.0/24", "10.0.0.0/16",
    ]
    with pytest.raises(ValidationError):
        ScanRequest(subnets=[f"10.{i}.0.0/24" for i in range(MAX_SCAN_SUBNETS + 1)])
    with pytest.raises(ValidationError):
        ScanRequest(ports=[0])


def test_scan_target_ips_is_bounded():
    assert len(scan_target_ips("10.0.0.0/16")) == 65534
    for subnet in ("0.0.0.0/0", "10.0.0.0/15", "fe80::/64"):
        with pytest.raises(ValueError):
            scan_target_ips(subnet)


@pytest.mark.asyncio
async def test_whole_internet_scan_refused_before_setup(client):
    # Before setup the wizard's scan route needs no credentials: the unauthenticated case
    res = await client.post("/api/scanner/start", json={"subnets": ["0.0.0.0/0"]})
    assert res.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/scanner/start", "/api/scanner/start-dashboard"])
async def test_whole_internet_scan_refused_after_setup(client, admin_token, path):
    res = await client.post(path, json={"subnets": ["0.0.0.0/0"]}, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("method, path", [
    ("GET", "/api/scanner/live-discovery"),
    ("POST", "/api/scanner/quick-subnet-scan"),
])
async def test_query_param_scans_are_bounded(client, admin_token, method, path):
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = await client.request(method, path, params={"subnets": "0.0.0.0/0"}, headers=headers)
    assert res.status_code == 422

    too_many = ",".join(f"10.{i}.0.0/24" for i in range(MAX_SCAN_SUBNETS + 1))
    res = await client.request(method, path, params={"subnets": too_many}, headers=headers)
    assert res.status_code == 422


def test_subnets_param_keeps_bare_prefixes():
    from app.api.scanner import _subnets_param

    assert _subnets_param("192.168.1, 10.0.0.0/16,192.168.1.0/24") == ["192.168.1.0/24", "10.0.0.0/16"]


@pytest.mark.asyncio
async def test_live_discovery_needs_scanner_start_scope(client, admin_token):
    # It is a GET, but it sweeps the network and stores the hosts it finds
    res = await client.post(
        "/api/auth/tokens",
        json={"name": "read only", "scopes": ["scanner:read"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = res.json()["token"]

    res = await client.get(
        "/api/scanner/live-discovery",
        params={"subnets": "192.168.1.0/24"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    assert "scanner:start" in res.json()["detail"]


def test_active_scan_gets_need_scanner_start():
    from app.api.auth import _required_scope_for

    assert _required_scope_for("/api/scanner/scan-ip", "GET") == "scanner:start"
    assert _required_scope_for("/api/scanner/live-discovery/", "GET") == "scanner:start"
    assert _required_scope_for("/api/scanner/status", "GET") == "scanner:read"
