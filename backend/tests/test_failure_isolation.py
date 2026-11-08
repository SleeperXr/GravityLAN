"""One bad item must not take the rest down: an agent report, the notification queue, refresh-all."""

import importlib.util
import sys
from collections import namedtuple
import threading
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import select

from app.api import devices as devices_api
from app.models.device import Device
from app.services import webhook_service

AGENT_PATH = Path(__file__).resolve().parent.parent.parent / "agent" / "gravitylan-agent.py"
LATIN1_APT = "Paketlisten werden gelesen f\xfcr\nInst nano [7.2] (8.0 Debian:13/stable [amd64])\n".encode("latin-1")


@pytest.fixture(scope="module")
def agent():
    spec = importlib.util.spec_from_file_location("gravitylan_agent_isolation", AGENT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- agent ----------------------------------------------------------------------------

def test_one_failing_collector_does_not_lose_the_report(agent, caplog):
    class Broken:
        def collect(self, config):
            raise UnicodeDecodeError("utf-8", b"\xfc", 0, 1, "invalid start byte")

    class Fine:
        def collect(self, config):
            return 42

    orchestrator = NS(config=NS(device_id=7), collectors={"patches": Broken(), "cpu_percent": Fine()})
    payload = agent.AgentOrchestrator.collect_all(orchestrator)

    assert (payload["device_id"], payload["cpu_percent"]) == (7, 42)
    assert "patches" not in payload
    assert "Collector patches failed" in caplog.text


def test_apt_output_that_is_not_utf8_is_still_counted(agent):
    result = {}
    with patch.object(agent, "_apt_cache_is_stale", return_value=False), \
            patch.object(agent.subprocess, "check_output", return_value=LATIN1_APT), \
            patch.object(agent.shutil, "which", return_value=None):
        agent.PatchMetrics()._collect_apt(result)
    assert (result["patch_available"], result["patch_security"]) == (1, 0)


def test_run_quiet_accepts_output_that_is_not_utf8(agent):
    with patch.object(agent.subprocess, "run", return_value=NS(stdout=LATIN1_APT)):
        assert "nano" in agent._run_quiet(["dnf", "check-update"])


def test_a_mount_name_that_is_not_utf8_keeps_the_other_mounts(agent, tmp_path):
    mounts = tmp_path / "mounts"
    mounts.write_bytes(b"/dev/sda1 /mnt/f\xfcr ext4 rw 0 0\n/dev/sdb1 /mnt/data ext4 rw 0 0\n")
    real_open = open

    def fake_open(path, *args, **kwargs):
        return real_open(mounts if path == "/proc/mounts" else path, *args, **kwargs)

    with patch("builtins.open", fake_open):
        assert "/mnt/data" in agent._discover_mount_targets(["/"])


# --- notification queue ---------------------------------------------------------------

def _entry(entry_id, url):
    return NS(id=entry_id, subscription_id=1, service_type="webhook", target_url=url, event_type="device.offline",
              payload='{"ip": "192.0.2.1"}', attempts=0, max_attempts=3, status="pending",
              last_error=None, delivered_at=None, next_attempt_at=None)


@pytest.mark.parametrize("error", [httpx.InvalidURL("bad url"), UnicodeEncodeError("ascii", "x", 0, 1, "no"), ValueError("bad")])
async def test_an_entry_that_cannot_be_sent_does_not_block_the_queue(error):
    stuck, behind = _entry(1, "http://198.51.100.1/stuck"), _entry(2, "http://198.51.100.1/behind")

    async def post(url, **_kwargs):
        if url.endswith("/stuck"):
            raise error
        return NS(status_code=200, text="")

    entries = MagicMock()
    entries.scalars.return_value.all.return_value = [stuck, behind]
    subscriptions = MagicMock()
    subscriptions.scalars.return_value.all.return_value = [NS(id=1, is_active=True, encrypted_token=None)]
    db = NS(execute=AsyncMock(side_effect=[entries, subscriptions]), commit=AsyncMock())

    with patch.object(webhook_service, "_blocked_target_reason", new=AsyncMock(return_value=None)), \
            patch.object(webhook_service, "_get_client", new=AsyncMock(return_value=NS(post=post))):
        assert await webhook_service.deliver_pending_outbox(db) == 1

    assert (stuck.attempts, stuck.status) == (1, "pending")
    assert stuck.last_error and stuck.next_attempt_at is not None
    assert behind.status == "delivered"
    assert db.commit.await_count == 2


# --- refresh-all ----------------------------------------------------------------------

class SameSession:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_exc):
        return False


async def _device(db, **fields):
    device = Device(**fields)
    db.add(device)
    await db.commit()
    return device


async def test_vendors_are_looked_up_off_the_event_loop_and_only_for_these_devices(db, monkeypatch):
    known = await _device(db, ip="192.0.2.60", mac="aa:aa:aa:aa:aa:60", display_name="a")
    found = await _device(db, ip="192.0.2.61", display_name="b")
    threads, asked = [], []

    def get_vendor(mac):
        threads.append(threading.current_thread())
        asked.append(mac)
        return "Acme"

    monkeypatch.setattr("app.database.async_session", lambda: SameSession(db))
    monkeypatch.setattr(devices_api, "get_vendor", get_vendor)

    mac_map = {"192.0.2.61": "bb:bb:bb:bb:bb:61", "192.0.2.99": "cc:cc:cc:cc:cc:99"}
    vendors = await devices_api._vendors_for([known.id, found.id], mac_map)

    assert vendors == {"aa:aa:aa:aa:aa:60": "Acme", "bb:bb:bb:bb:bb:61": "Acme"}
    assert sorted(asked) == ["aa:aa:aa:aa:aa:60", "bb:bb:bb:bb:bb:61"]
    assert threading.main_thread() not in threads


async def test_a_device_that_fails_does_not_cost_the_others(db, monkeypatch):
    bad = await _device(db, ip="192.0.2.70", display_name="bad", hostname="old.lan")
    good = await _device(db, ip="192.0.2.71", display_name="good", hostname="old.lan")

    async def resolve(ip, **_kwargs):
        if ip == "192.0.2.70":
            raise ValueError("no")
        return "new.lan"

    async def arp(hosts, *_args, **_kwargs):
        return hosts

    monkeypatch.setattr("app.database.async_session", lambda: SameSession(db))
    monkeypatch.setattr("app.scanner.arp.resolve_mac_addresses", arp)
    monkeypatch.setattr("app.scanner.hostname.resolve_hostname", resolve)
    monkeypatch.setattr(devices_api, "get_vendor", lambda mac: "")

    Row = namedtuple("Row", "id ip display_name")
    await devices_api._bulk_metadata_refresh([Row(bad.id, bad.ip, "bad"), Row(good.id, good.ip, "good")], (None, None))

    names = dict((await db.execute(select(Device.ip, Device.hostname))).all())
    assert names == {"192.0.2.70": "old.lan", "192.0.2.71": "new.lan"}
