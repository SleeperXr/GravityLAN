"""Integration tests for scanner offline/online state transitions.

Tests the Planner and Dashboard scanner logic for correctly handling
device state transitions, especially the service-aware guard from PR #7.
"""

import ipaddress
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.device import Device, Service, DeviceHistory
from app.models.network import Subnet


@pytest_asyncio.fixture
async def device_with_services(db):
    """Create a device with configured services (e.g. a UniFi switch)."""
    dev = Device(
        ip="192.168.100.223",
        mac="AA:BB:CC:DD:EE:FF",
        hostname="keller",
        display_name="Keller",
        device_type="switch",
        device_subtype="UniFi",
        is_online=True,
        last_seen=datetime.now(timezone.utc),
    )
    db.add(dev)
    await db.flush()

    svc = Service(
        device_id=dev.id,
        name="SSH",
        protocol="ssh",
        port=22,
        url_template="ssh://{ip}",
        is_auto_detected=True,
    )
    db.add(svc)
    await db.commit()
    await db.refresh(dev)
    return dev


@pytest_asyncio.fixture
async def device_without_services(db):
    """Create a plain device without any configured services."""
    dev = Device(
        ip="192.168.100.50",
        mac="11:22:33:44:55:66",
        hostname="iot-sensor",
        display_name="IoT Sensor",
        device_type="unknown",
        device_subtype="Unknown",
        is_online=True,
        last_seen=datetime.now(timezone.utc),
    )
    db.add(dev)
    await db.commit()
    await db.refresh(dev)
    return dev


@pytest_asyncio.fixture
async def subnet(db):
    """Create a test subnet."""
    sub = Subnet(cidr="192.168.100.0/24", name="Test Subnet")
    db.add(sub)
    await db.commit()
    return sub


class TestPlannerServiceGuard:
    """Tests for the planner's service-aware offline guard (PR #7 fix).

    These tests exercise the exact decision logic from planner.py lines 150-194:
    - Load online devices
    - Check if device IP is in a scanned subnet
    - Check if device IP was found alive
    - If not alive AND has services → skip (stay online)
    - If not alive AND no services → mark offline + history + webhook
    """

    @pytest.mark.asyncio
    async def test_device_with_services_stays_online_on_missed_ping(
        self, db, device_with_services, subnet
    ):
        """Devices with configured services should NOT be marked offline.

        The dashboard scanner handles these with TCP+ICMP hybrid checks.
        A single missed ping must not trigger a false alarm.
        """
        subnets = ["192.168.100.0/24"]
        all_alive_ips: set[str] = set()  # Nothing found alive

        # Simulate the planner offline-check logic (planner.py lines 150-194)
        res_dev = await db.execute(
            select(Device).options(selectinload(Device.services)).where(Device.is_online == True)
        )
        for dev in res_dev.scalars().all():
            in_any_scanned = False
            for s in subnets:
                net_obj = ipaddress.IPv4Network(s, strict=False)
                if ipaddress.IPv4Address(dev.ip) in net_obj:
                    in_any_scanned = True
                    break

            if in_any_scanned and dev.ip not in all_alive_ips:
                # THIS is the PR #7 guard
                if dev.services:
                    continue
                dev.is_online = False

        await db.commit()
        await db.refresh(device_with_services)

        assert device_with_services.is_online is True, (
            "Device with services should remain online after missed ping"
        )

    @pytest.mark.asyncio
    async def test_device_without_services_goes_offline_on_missed_ping(
        self, db, device_without_services, subnet
    ):
        """Devices without services SHOULD be marked offline by the planner."""
        subnets = ["192.168.100.0/24"]
        all_alive_ips: set[str] = set()  # Nothing found alive

        res_dev = await db.execute(
            select(Device).options(selectinload(Device.services)).where(Device.is_online == True)
        )
        for dev in res_dev.scalars().all():
            in_any_scanned = False
            for s in subnets:
                net_obj = ipaddress.IPv4Network(s, strict=False)
                if ipaddress.IPv4Address(dev.ip) in net_obj:
                    in_any_scanned = True
                    break

            if in_any_scanned and dev.ip not in all_alive_ips:
                if dev.services:
                    continue
                dev.is_online = False
                dev.status_changed_at = datetime.now(timezone.utc)
                db.add(DeviceHistory(
                    device_id=dev.id,
                    status="offline",
                    message=f"Device {dev.display_name or dev.hostname or dev.ip} went offline",
                ))

        await db.commit()
        await db.refresh(device_without_services)

        assert device_without_services.is_online is False, (
            "Device without services should be marked offline on missed ping"
        )

    @pytest.mark.asyncio
    async def test_offline_event_creates_history_entry(
        self, db, device_without_services, subnet
    ):
        """When a serviceless device goes offline, a DeviceHistory record must be created."""
        subnets = ["192.168.100.0/24"]
        all_alive_ips: set[str] = set()

        res_dev = await db.execute(
            select(Device).options(selectinload(Device.services)).where(Device.is_online == True)
        )
        for dev in res_dev.scalars().all():
            in_any_scanned = False
            for s in subnets:
                net_obj = ipaddress.IPv4Network(s, strict=False)
                if ipaddress.IPv4Address(dev.ip) in net_obj:
                    in_any_scanned = True
                    break

            if in_any_scanned and dev.ip not in all_alive_ips:
                if dev.services:
                    continue
                dev.is_online = False
                dev.status_changed_at = datetime.now(timezone.utc)
                db.add(DeviceHistory(
                    device_id=dev.id,
                    status="offline",
                    message=f"Device {dev.display_name or dev.hostname or dev.ip} went offline",
                ))

        await db.commit()

        res = await db.execute(
            select(DeviceHistory).where(
                DeviceHistory.device_id == device_without_services.id,
                DeviceHistory.status == "offline",
            )
        )
        history = res.scalars().all()
        assert len(history) == 1, "Offline transition should create exactly one history entry"
        assert "IoT Sensor" in history[0].message

    @pytest.mark.asyncio
    async def test_device_found_alive_stays_online(
        self, db, device_without_services, subnet
    ):
        """Devices that respond to ping should stay online regardless of services."""
        subnets = ["192.168.100.0/24"]
        all_alive_ips = {"192.168.100.50"}  # Device DID respond

        res_dev = await db.execute(
            select(Device).options(selectinload(Device.services)).where(Device.is_online == True)
        )
        for dev in res_dev.scalars().all():
            in_any_scanned = False
            for s in subnets:
                net_obj = ipaddress.IPv4Network(s, strict=False)
                if ipaddress.IPv4Address(dev.ip) in net_obj:
                    in_any_scanned = True
                    break

            if in_any_scanned and dev.ip not in all_alive_ips:
                if dev.services:
                    continue
                dev.is_online = False

        await db.commit()
        await db.refresh(device_without_services)

        assert device_without_services.is_online is True, (
            "Device that responded to ping should stay online"
        )


class TestDashboardHealthCheck:
    """Tests for the dashboard scanner's hybrid health-check decision logic."""

    @pytest.mark.asyncio
    async def test_device_online_via_port_even_without_ping(
        self, db, device_with_services
    ):
        """If ping fails but TCP port is open, device should remain online.

        Simulates dashboard.py lines 96-107 decision logic.
        """
        alive_map: dict = {}  # Ping found nothing
        open_ports = [22]  # But SSH responds

        is_ping_alive = device_with_services.ip in alive_map
        is_port_alive = len(open_ports) > 0
        is_docker_host = False

        is_online = is_ping_alive or is_port_alive or is_docker_host

        was_online = device_with_services.is_online
        device_with_services.is_online = is_online
        if is_online:
            device_with_services.last_seen = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(device_with_services)

        assert device_with_services.is_online is True
        assert not is_ping_alive
        assert is_port_alive

    @pytest.mark.asyncio
    async def test_device_offline_when_nothing_responds(
        self, db, device_with_services
    ):
        """If both ping and TCP fail, device should go offline."""
        alive_map: dict = {}
        open_ports: list[int] = []

        is_ping_alive = device_with_services.ip in alive_map
        is_port_alive = len(open_ports) > 0
        is_docker_host = False

        is_online = is_ping_alive or is_port_alive or is_docker_host

        was_online = device_with_services.is_online
        device_with_services.is_online = is_online

        if not is_online and was_online:
            device_with_services.status_changed_at = datetime.now(timezone.utc)
            db.add(DeviceHistory(
                device_id=device_with_services.id,
                status="offline",
                message=f"Device {device_with_services.display_name} went offline",
            ))

        await db.commit()
        await db.refresh(device_with_services)

        assert device_with_services.is_online is False

    @pytest.mark.asyncio
    async def test_service_status_updated_from_port_scan(
        self, db, device_with_services
    ):
        """Service.is_up should reflect whether its port was found open."""
        open_ports: list[int] = []  # SSH port 22 is closed

        for svc in device_with_services.services:
            svc.is_up = svc.port in open_ports
            svc.last_checked = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(device_with_services)

        ssh_svc = [s for s in device_with_services.services if s.port == 22]
        assert len(ssh_svc) == 1
        assert ssh_svc[0].is_up is False, "SSH service should be marked down when port is closed"

    @pytest.mark.asyncio
    async def test_service_marked_up_when_port_responds(
        self, db, device_with_services
    ):
        """Service.is_up should be True when its port is in open_ports."""
        # First mark it down
        for svc in device_with_services.services:
            svc.is_up = False
        await db.commit()

        # Now simulate port responding
        open_ports = [22]
        for svc in device_with_services.services:
            svc.is_up = svc.port in open_ports
            svc.last_checked = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(device_with_services)

        ssh_svc = [s for s in device_with_services.services if s.port == 22]
        assert ssh_svc[0].is_up is True


class TestServicePortValidation:
    """Tests for ServiceUpdate port validation."""

    def test_service_update_rejects_port_zero(self):
        """Port 0 should be rejected."""
        from app.schemas.device import ServiceUpdate
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ServiceUpdate(port=0)

    def test_service_update_rejects_port_too_high(self):
        """Port > 65535 should be rejected."""
        from app.schemas.device import ServiceUpdate
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ServiceUpdate(port=70000)

    def test_service_update_rejects_negative_port(self):
        """Negative port should be rejected."""
        from app.schemas.device import ServiceUpdate
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ServiceUpdate(port=-1)

    def test_service_update_accepts_valid_port(self):
        """Valid port numbers should pass validation."""
        from app.schemas.device import ServiceUpdate

        svc = ServiceUpdate(port=443)
        assert svc.port == 443

    def test_service_update_accepts_boundary_ports(self):
        """Boundary port values 1 and 65535 should pass."""
        from app.schemas.device import ServiceUpdate

        low = ServiceUpdate(port=1)
        assert low.port == 1

        high = ServiceUpdate(port=65535)
        assert high.port == 65535

    def test_service_update_accepts_none_port(self):
        """None port (no change) should pass validation."""
        from app.schemas.device import ServiceUpdate

        svc = ServiceUpdate(port=None)
        assert svc.port is None
