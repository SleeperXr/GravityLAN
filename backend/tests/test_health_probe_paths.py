"""Health probe paths (app/scanner/health_probe.py) the pass tests do not reach: TCP instead of ICMP,
the fallback ports of devices without services, empty inventories, failing probes and missed scans."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.device import Device, DeviceHealthSample, Service
from app.scanner import health_probe as hp
from app.scanner.presence import FALLBACK_PROBE_PORTS

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _dev(services=()):
    return SimpleNamespace(id=1, ip="192.0.2.10", hostname="host.lan", services=list(services))


def _no_ping(monkeypatch):
    async def no_answer(ip, timeout):
        return None

    monkeypatch.setattr(hp, "measure_ping_latency_ms", no_answer)


@pytest.mark.asyncio
async def test_without_ping_the_fastest_open_service_counts(monkeypatch):
    _no_ping(monkeypatch)
    rtts = {11: 9.0, 12: 4.0, 13: None}

    async def probe(ip, hostname, svc, now):
        return svc.id, rtts[svc.id], None, False

    monkeypatch.setattr(hp, "_probe_single_service", probe)
    sample, results = await hp._probe_single_device(_dev([SimpleNamespace(id=i) for i in rtts]), NOW, asyncio.Semaphore(1))
    assert (sample.is_online, sample.probe_type, sample.latency_ms) == (True, "tcp", 4.0)
    assert (sample.ports_up, sample.ports_total) == (2, 3)
    assert results[13] == (None, None, False)


@pytest.mark.asyncio
async def test_a_device_without_services_is_tried_on_the_fallback_ports(monkeypatch):
    _no_ping(monkeypatch)
    tried = []

    async def tcp(ip, port, timeout):
        tried.append(port)
        return 7.5 if port == FALLBACK_PROBE_PORTS[-1] else None

    monkeypatch.setattr(hp, "measure_tcp_latency_ms", tcp)
    sample, _ = await hp._probe_single_device(_dev(), NOW, asyncio.Semaphore(1))
    assert sorted(tried) == sorted(FALLBACK_PROBE_PORTS)
    assert (sample.is_online, sample.probe_type, sample.latency_ms) == (True, "tcp", 7.5)

    async def closed(ip, port, timeout):
        return None

    monkeypatch.setattr(hp, "measure_tcp_latency_ms", closed)
    sample, _ = await hp._probe_single_device(_dev(), NOW, asyncio.Semaphore(1))
    assert (sample.is_online, sample.probe_type, sample.latency_ms) == (False, None, None)


@pytest.fixture
def probe_db(db, monkeypatch):
    @asynccontextmanager
    async def same_session():
        yield db

    monkeypatch.setattr(hp, "async_session", same_session)
    return db


@pytest.mark.asyncio
async def test_a_pass_over_no_devices_samples_nothing(probe_db):
    assert await hp.run_health_probe_pass() == 0


@pytest.mark.asyncio
async def test_a_failing_probe_skips_only_that_device(probe_db, monkeypatch):
    ok = Device(ip="192.0.2.11", display_name="ok")
    broken = Device(ip="192.0.2.12", display_name="broken")
    probe_db.add_all([ok, broken])
    await probe_db.commit()
    real = hp._probe_single_device

    async def probe(dev, now, semaphore):
        if dev.ip == broken.ip:
            raise OSError("probe crashed")
        return await real(dev, now, semaphore)

    async def ping(ip, timeout):
        return 1.0

    monkeypatch.setattr(hp, "_probe_single_device", probe)
    monkeypatch.setattr(hp, "measure_ping_latency_ms", ping)
    assert await hp.run_health_probe_pass() == 1
    sampled = (await probe_db.execute(select(DeviceHealthSample.device_id))).scalars().all()
    assert sampled == [ok.id]


@pytest.mark.asyncio
async def test_an_unreachable_device_with_services_and_no_agent_counts_a_miss(probe_db, monkeypatch):
    dev = Device(ip="192.0.2.13", display_name="nas", is_online=True, missed_scans=0)
    probe_db.add(dev)
    await probe_db.flush()
    probe_db.add(Service(device_id=dev.id, name="Web", protocol="http", port=80))
    await probe_db.commit()
    _no_ping(monkeypatch)

    async def down(ip, hostname, svc, now):
        return svc.id, None, None, False

    misses = []

    async def register_miss(device, db, threshold):
        misses.append(device.id)

    monkeypatch.setattr(hp, "_probe_single_service", down)
    monkeypatch.setattr(hp, "register_miss", register_miss)
    assert await hp.run_health_probe_pass() == 1
    assert misses == [dev.id]


# --- a slow service gets a second try --------------------------------------------------------------

def _svc():
    return SimpleNamespace(id=21, port=8080, protocol="http", ignore_ssl=True, ssl_checked_at=None)


@pytest.mark.asyncio
async def test_a_service_that_misses_once_is_tried_again_more_patiently(monkeypatch):
    timeouts = []

    async def tcp(ip, port, timeout):
        timeouts.append(timeout)
        return None if len(timeouts) == 1 else 12.0

    monkeypatch.setattr(hp, "measure_tcp_latency_ms", tcp)
    assert await hp._probe_single_service("192.0.2.10", None, _svc(), NOW) == (21, 12.0, None, False)
    assert timeouts == [hp.SERVICE_PROBE_TIMEOUT, hp.SERVICE_RETRY_TIMEOUT]


@pytest.mark.asyncio
async def test_a_service_that_misses_twice_is_down_and_an_answer_needs_no_retry(monkeypatch):
    calls = []

    async def silent(ip, port, timeout):
        calls.append(timeout)
        return None

    monkeypatch.setattr(hp, "measure_tcp_latency_ms", silent)
    assert (await hp._probe_single_service("192.0.2.10", None, _svc(), NOW))[1] is None
    assert len(calls) == 2

    calls.clear()

    async def quick(ip, port, timeout):
        calls.append(timeout)
        return 3.0

    monkeypatch.setattr(hp, "measure_tcp_latency_ms", quick)
    assert (await hp._probe_single_service("192.0.2.10", None, _svc(), NOW))[1] == 3.0
    assert len(calls) == 1
