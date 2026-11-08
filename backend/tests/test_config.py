"""Tests for the application configuration (app/config.py)."""

import os
from pathlib import Path

import pytest

from app.config import Settings, _default_data_dir, process_ids


# --- field validators -------------------------------------------------------

def test_validate_scan_timeout_positive():
    s = Settings(scan_timeout=1.5)
    assert s.scan_timeout == 1.5


def test_validate_scan_timeout_rejects_non_positive():
    with pytest.raises(ValueError):
        Settings(scan_timeout=0)
    with pytest.raises(ValueError):
        Settings(scan_timeout=-1)


def test_validate_scan_workers_bounds():
    assert Settings(scan_workers=1).scan_workers == 1
    assert Settings(scan_workers=200).scan_workers == 200
    with pytest.raises(ValueError):
        Settings(scan_workers=0)
    with pytest.raises(ValueError):
        Settings(scan_workers=201)


def test_validate_scan_interval_non_negative():
    assert Settings(scan_interval_minutes=0).scan_interval_minutes == 0
    with pytest.raises(ValueError):
        Settings(scan_interval_minutes=-1)


def test_validate_history_retention_bounds():
    assert Settings(history_retention_days=1).history_retention_days == 1
    assert Settings(history_retention_days=365).history_retention_days == 365
    with pytest.raises(ValueError):
        Settings(history_retention_days=0)
    with pytest.raises(ValueError):
        Settings(history_retention_days=366)


def test_validate_port_bounds():
    assert Settings(port=8000).port == 8000
    assert Settings(port=1).port == 1
    assert Settings(port=65535).port == 65535
    with pytest.raises(ValueError):
        Settings(port=0)
    with pytest.raises(ValueError):
        Settings(port=65536)


# --- host validation --------------------------------------------------------

@pytest.mark.parametrize("host", ["0.0.0.0", "::", "localhost"])
def test_validate_host_special_values(host):
    assert Settings(host=host).host == host


@pytest.mark.parametrize("host", ["192.168.1.10", "10.0.0.1", "127.0.0.1"])
def test_validate_host_ipv4(host):
    assert Settings(host=host).host == host


@pytest.mark.parametrize("host", ["fe80::1", "2001:db8::1"])
def test_validate_host_ipv6(host):
    assert Settings(host=host).host == host


@pytest.mark.parametrize("host", ["myhost", "my.host.local", "web-01.example.com"])
def test_validate_host_hostname(host):
    assert Settings(host=host).host == host


@pytest.mark.parametrize(
    "host",
    ["", "   ", "bad_host!", "exa mple", "my..host", "-invalid-", "-host", "host-", "my.-host.local", "web.example-", "-"],
)
def test_validate_host_rejects_invalid(host):
    with pytest.raises(ValueError):
        Settings(host=host)


def test_validate_host_trims_whitespace():
    assert Settings(host=" 192.168.1.10 ").host == "192.168.1.10"


@pytest.mark.parametrize(
    ("host", "message"),
    [
        ("   ", "host cannot be empty"),
        ("a" * 254, "host name is too long"),
        ("my..host", "host labels cannot be empty"),
        ("a" * 64, "host label is too long"),
        ("-host", "host labels must start and end with an alphanumeric character"),
        ("host-", "host labels must start and end with an alphanumeric character"),
        ("bad_host", "host name contains invalid characters"),
    ],
)
def test_validate_host_error_messages(host, message):
    with pytest.raises(ValueError, match=message):
        Settings(host=host)


def test_validate_host_reports_first_failing_label():
    # The first bad label decides the error, and the length limit comes before the label checks.
    with pytest.raises(ValueError, match="host labels cannot be empty"):
        Settings(host=f".{'a' * 64}")
    with pytest.raises(ValueError, match="host label is too long"):
        Settings(host=f"{'a' * 64}.")
    with pytest.raises(ValueError, match="host name is too long"):
        Settings(host=".".join(["a..b"] * 60))


@pytest.mark.parametrize("host", ["a" * 63, ".".join(["a" * 63] * 3) + "." + "a" * 61, "1-a.b2"])
def test_validate_host_accepts_length_limits(host):
    assert Settings(host=host).host == host


def test_validate_host_malformed_ip_falls_through_to_hostname_rules():
    # Not an IPv4 address, but still a valid RFC 1123 name.
    assert Settings(host="999.1.1.1").host == "999.1.1.1"
    # Not an IPv6 address, and ":" is not allowed in a host name.
    with pytest.raises(ValueError, match="host name contains invalid characters"):
        Settings(host="fe80:::1")


# --- module helpers ---------------------------------------------------------

def test_default_data_dir_inside_container(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    assert _default_data_dir() == Path("/app/data")


def test_default_data_dir_outside_container(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda self: False)
    assert _default_data_dir() == Path("./data")


def test_process_ids_uses_posix_ids(monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 99, raising=False)
    monkeypatch.setattr(os, "getgid", lambda: 100, raising=False)
    assert process_ids() == (99, 100)


def test_process_ids_falls_back_without_posix_ids(monkeypatch):
    monkeypatch.delattr(os, "getuid", raising=False)
    monkeypatch.delattr(os, "getgid", raising=False)
    assert process_ids() == (1000, 1000)


# --- telemetry_database_path ------------------------------------------------

def test_telemetry_database_path_next_to_sqlite_inventory():
    s = Settings(database_url="sqlite+aiosqlite:////data/gravitylan.db")
    assert Path(s.telemetry_database_path) == Path("/data/telemetry.db")


def test_telemetry_database_path_empty_for_other_databases():
    assert Settings(database_url="postgresql+asyncpg://db/gravitylan").telemetry_database_path == ""


@pytest.mark.parametrize("url", ["sqlite+aiosqlite:///:memory:", "sqlite+aiosqlite://", "sqlite+aiosqlite:///"])
def test_telemetry_database_path_in_memory(url):
    assert Settings(database_url=url).telemetry_database_path == ":memory:"


# --- effective_database_url -------------------------------------------------

def test_effective_database_url_uses_configured():
    s = Settings(database_url="sqlite+aiosqlite:////tmp/custom.db")
    assert s.effective_database_url == "sqlite+aiosqlite:////tmp/custom.db"


def test_effective_database_url_defaults_to_data_dir(tmp_path):
    s = Settings(data_dir=tmp_path, database_url="")
    assert s.effective_database_url == f"sqlite+aiosqlite:///{tmp_path / 'gravitylan.db'}"


def test_settings_module_singleton():
    from app.config import settings as module_settings
    assert isinstance(module_settings, Settings)
