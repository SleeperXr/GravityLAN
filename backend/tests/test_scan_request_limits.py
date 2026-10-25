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
