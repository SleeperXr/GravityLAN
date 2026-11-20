"""Backup import: settings and subnets pass the app's input checks; the scheduler pauses meanwhile."""

import json

import pytest

from app.api import backup
from tests.test_backup_import import _post_backup, _query, _settings, backup_db, import_endpoint_db  # noqa: F401  (fixtures)


def test_settings_that_fail_their_check_are_left_out(backup_db):  # noqa: F811
    report: dict = {}
    imported = backup._write_db(backup_db, {"settings": [
        {"key": "dns.server", "value": "--script=evil"},  # would reach nmap
        {"key": "server.url", "value": "http://x/install?$(id)"},  # would reach the install script
        {"key": "ui.start_page", "value": "javascript:alert(1)"},
        {"key": "scan_interval", "value": "30"},  # no check of its own
        {"key": "dns.server_secondary", "value": "9.9.9.9"},
        {"key": "ui.health_resilience", "value": ""},  # empty: not checked, as in POST /api/settings
    ]}, report)

    stored = _settings(backup_db)
    assert "dns.server" not in stored and "server.url" not in stored and "ui.start_page" not in stored
    assert stored["scan_interval"] == "30" and stored["dns.server_secondary"] == "9.9.9.9"
    assert report["invalid_dropped"] == {"app_settings": 3}
    assert imported["app_settings"] == 3


def test_subnets_are_checked_and_normalized_like_new_ones(backup_db):  # noqa: F811
    report: dict = {}
    backup._write_db(backup_db, {"subnets": [
        {"id": 1, "cidr": "192.168.5", "name": "Lab", "is_enabled": 1},
        {"id": 2, "cidr": "10.0.0.0/8", "name": "Too big"},
        {"id": 3, "cidr": "192.168.7.0/24", "name": "Bad DNS", "dns_server": "8.8.8.8 --script=x"},
        {"id": 4, "cidr": "192.168.9.5/24", "name": "", "gateway_ip": "192.168.9.1", "dns_server": " 1.1.1.1 "},
        {"id": 5, "cidr": "192.168.10.0/24", "name": "Wrong gateway", "gateway_ip": "192.168.11.1"},
        {"id": 6, "cidr": "not a network", "name": "x"},
    ]}, report)

    rows = _query(backup_db, "SELECT id, cidr, name, dns_server, gateway_ip FROM subnets ORDER BY id")
    assert rows == [
        (1, "192.168.5.0/24", "Lab", None, None),
        (4, "192.168.9.0/24", "Network 192.168.9.0/24", "1.1.1.1", "192.168.9.1"),
    ]
    assert report["invalid_dropped"] == {"subnets": 4}


def test_a_backup_whose_subnets_all_fail_keeps_the_current_ones(backup_db):  # noqa: F811
    backup._write_db(backup_db, {"subnets": [{"id": 1, "cidr": "192.168.1.0/24", "name": "LAN"}]})
    backup._write_db(backup_db, {"subnets": [{"id": 9, "cidr": "0.0.0.0/0", "name": "Everything"}]})
    assert _query(backup_db, "SELECT cidr FROM subnets") == [("192.168.1.0/24",)]


@pytest.mark.asyncio
async def test_the_import_reports_what_it_left_out(client, admin_token, import_endpoint_db):  # noqa: F811
    payload = json.dumps({"settings": [{"key": "dns.server", "value": "evil"}, {"key": "scan_interval", "value": "7"}]})

    res = await _post_backup(client, admin_token, payload.encode())

    assert res.status_code == 200
    assert res.json()["invalid_dropped"] == {"app_settings": 1}
    assert "left out" in res.json()["message"]


class _FakeScheduler:
    def __init__(self, running: bool, events: list):
        self._running, self.events = running, events

    @property
    def running(self):
        return self._running

    async def stop(self):
        self.events.append("stop")
        self._running = False

    async def start(self):
        self.events.append("start")
        self._running = True


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_the_scheduler_pauses_while_the_tables_are_replaced(
    client, admin_token, import_endpoint_db, monkeypatch, fails,  # noqa: F811
):
    events: list = []
    fake = _FakeScheduler(True, events)
    monkeypatch.setattr("app.scanner.scheduler.scheduler", fake)
    real_write = backup._write_db

    def write(*args, **kwargs):
        events.append("write")
        if fails:
            raise RuntimeError("disk full")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(backup, "_write_db", write)
    res = await _post_backup(client, admin_token, json.dumps({"settings": []}).encode())

    assert res.status_code == (500 if fails else 200)
    assert events == ["stop", "write", "start"]  # restarted also after a failed import
    assert fake.running


@pytest.mark.asyncio
async def test_a_scheduler_that_was_not_running_stays_off(client, admin_token, import_endpoint_db, monkeypatch):  # noqa: F811
    events: list = []
    monkeypatch.setattr("app.scanner.scheduler.scheduler", _FakeScheduler(False, events))

    res = await _post_backup(client, admin_token, json.dumps({"settings": []}).encode())

    assert res.status_code == 200
    assert events == []
