"""Tests for the device-related Pydantic schemas (app/schemas/device.py)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.device import (
    ServiceCreate,
    ServiceResponse,
    ServiceUpdate,
    DeviceHistoryResponse,
    DeviceResponse,
    DeviceUpdate,
    GroupCreate,
    GroupUpdate,
    DiscoveredHostResponse,
    DiscoveredHostUpdate,
)


# --- ServiceCreate ----------------------------------------------------------

def test_service_create_valid():
    svc = ServiceCreate(name="HTTP", protocol="tcp", port=80)
    assert svc.name == "HTTP"
    assert svc.port == 80
    assert svc.is_auto_detected is False
    assert svc.sort_order == 0


def test_service_create_requires_name():
    with pytest.raises(ValidationError):
        ServiceCreate(name="", port=80)


def test_service_create_port_bounds():
    with pytest.raises(ValidationError):
        ServiceCreate(name="x", port=0)
    with pytest.raises(ValidationError):
        ServiceCreate(name="x", port=65536)


# --- ServiceUpdate ----------------------------------------------------------

def test_service_update_partial():
    svc = ServiceUpdate(name="New Name")
    assert svc.name == "New Name"
    assert svc.port is None


def test_service_update_invalid_port():
    with pytest.raises(ValidationError):
        ServiceUpdate(port=70000)


# --- ServiceResponse --------------------------------------------------------

def test_service_response_from_attributes():
    svc = ServiceResponse(
        id=1, name="SSH", protocol="tcp", port=22, url_template="ssh://{ip}"
    )
    assert svc.is_up is True  # default
    assert svc.last_checked is None  # default


# --- DeviceHistoryResponse --------------------------------------------------

def test_device_history_response_defaults():
    ts = datetime.now(timezone.utc)
    hist = DeviceHistoryResponse(id=1, device_id=5, status="online", timestamp=ts)
    assert hist.service_id is None
    assert hist.message is None


# --- DeviceResponse ---------------------------------------------------------

def test_device_response_defaults():
    ts = datetime.now(timezone.utc)
    dev = DeviceResponse(
        id=1,
        ip="192.168.1.10",
        display_name="test",
        device_type="server",
        device_subtype="Server",
        first_seen=ts,
        last_seen=ts,
    )
    assert dev.is_online is True
    assert dev.is_hidden is False
    assert dev.services == []
    assert dev.ip_placeholder is False


# --- GroupCreate / GroupUpdate ----------------------------------------------

def test_group_create_valid_color():
    g = GroupCreate(name="Servers", color="#ff0000")
    assert g.color == "#ff0000"


def test_group_create_invalid_color():
    with pytest.raises(ValidationError):
        GroupCreate(name="x", color="red")


def test_group_update_empty_ok():
    g = GroupUpdate()
    assert g.name is None


# --- DiscoveredHostResponse -------------------------------------------------

def test_discovered_host_response_defaults():
    ts = datetime.now(timezone.utc)
    host = DiscoveredHostResponse(
        id=1, ip="10.0.0.5", first_seen=ts, last_seen=ts
    )
    assert host.is_online is True
    assert host.is_monitored is False
    assert host.is_reserved is False


def test_discovered_host_update_partial():
    upd = DiscoveredHostUpdate(custom_name="Router")
    assert upd.custom_name == "Router"
    assert upd.is_monitored is None
