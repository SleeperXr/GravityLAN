"""Tests for schema migrations and corrupted-IP repair logic."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, text

import app.database.migrations as migrations
from app.models.device import Device, DiscoveredHost


@pytest.fixture
def docker_unavailable(monkeypatch):
    docker_service = MagicMock()
    docker_service.is_available.return_value = False
    monkeypatch.setattr("app.services.docker_service.docker_service", docker_service)
    return docker_service


async def test_repair_device_known_container_id(db, docker_unavailable):
    db.add(Device(id=27, ip="offline-aa:bb:cc", ip_placeholder=True, display_name=""))
    await db.commit()

    await migrations._clean_corrupted_ip_placeholders(db)
    await db.commit()

    dev = (await db.execute(select(Device))).scalar_one()
    assert dev.ip == "192.168.100.241"
    assert dev.is_online is True
    assert dev.ip_placeholder is False


async def test_repair_device_keyword_map(db, docker_unavailable):
    db.add(Device(ip="offline-aa:bb:cc", ip_placeholder=True, display_name="Nextcloud"))
    await db.commit()

    await migrations._clean_corrupted_ip_placeholders(db)
    await db.commit()

    dev = (await db.execute(select(Device))).scalar_one()
    assert dev.ip == "192.168.100.231"
    assert dev.is_online is True
    assert dev.ip_placeholder is False


async def test_repair_device_restores_old_ip(db, docker_unavailable):
    db.add(Device(ip="offline-aa:bb:cc", ip_placeholder=True, display_name="", old_ip="192.168.5.50"))
    await db.commit()

    await migrations._clean_corrupted_ip_placeholders(db)
    await db.commit()

    dev = (await db.execute(select(Device))).scalar_one()
    assert dev.ip == "192.168.5.50"
    assert dev.is_online is False
    assert dev.ip_placeholder is True


async def test_repair_device_fallback_unique_placeholder(db, docker_unavailable):
    db.add(Device(ip="offline-aa:bb:cc", ip_placeholder=True, display_name=""))
    db.add(Device(ip="offline-dd:ee:ff", ip_placeholder=True, display_name=""))
    await db.commit()

    await migrations._clean_corrupted_ip_placeholders(db)
    await db.commit()

    devs = (await db.execute(select(Device))).scalars().all()
    assert sorted(d.ip for d in devs) == ["0.0.0.0", "0.0.0.1"]
    assert all(d.is_online is False and d.ip_placeholder is True for d in devs)


async def test_repair_device_skips_taken_keyword_ip(db, docker_unavailable):
    db.add(Device(ip="192.168.100.231", display_name="Real Nextcloud"))
    db.add(Device(ip="offline-aa:bb:cc", ip_placeholder=True, display_name="nextcloud", old_ip="10.0.0.9"))
    await db.commit()

    await migrations._clean_corrupted_ip_placeholders(db)
    await db.commit()

    devs = {d.display_name: d for d in (await db.execute(select(Device))).scalars().all()}
    assert devs["Real Nextcloud"].ip == "192.168.100.231"
    repaired = devs["nextcloud"]
    # Keyword IP taken -> old_ip restore strategy wins
    assert repaired.ip == "10.0.0.9"
    assert repaired.is_online is False
    assert repaired.ip_placeholder is True


async def test_repair_discovered_host_docker_match(db, monkeypatch):
    docker_service = MagicMock()
    docker_service.is_available.return_value = True
    docker_service.get_local_containers.return_value = [
        {"name": "Redis", "ips": ["10.0.0.5"], "status": "running"},
        {"name": "Stopped", "ips": ["10.0.0.6"], "status": "exited"},
    ]
    monkeypatch.setattr("app.services.docker_service.docker_service", docker_service)

    db.add(DiscoveredHost(ip="offline-aa:bb:cc", ip_placeholder=True, custom_name="redis"))
    await db.commit()

    await migrations._clean_corrupted_ip_placeholders(db)
    await db.commit()

    host = (await db.execute(select(DiscoveredHost))).scalar_one()
    assert host.ip == "10.0.0.5"
    assert host.is_online is True
    assert host.ip_placeholder is False


async def test_repair_discovered_host_fallback(db, docker_unavailable):
    db.add(DiscoveredHost(ip="offline-aa:bb:cc", ip_placeholder=True, custom_name="mystery"))
    await db.commit()

    await migrations._clean_corrupted_ip_placeholders(db)
    await db.commit()

    host = (await db.execute(select(DiscoveredHost))).scalar_one()
    assert host.ip == "0.0.0.0"
    assert host.is_online is False
    assert host.ip_placeholder is True


async def test_run_migrations_noop_on_fresh_schema(db, docker_unavailable):
    # conftest already created the full schema; nothing to alter, but it must run clean.
    await migrations.run_migrations(db)

    rows = (await db.execute(text("PRAGMA table_info(devices)"))).all()
    names = {r[1] for r in rows}
    assert {"topology_x", "max_ports", "ip_placeholder"} <= names
