"""TZ only works when the image has the zone file; without tzdata the log silently stays UTC."""
import logging
from pathlib import Path

import pytest

from app import timezone_check

ROOT = Path(__file__).resolve().parents[2]


def test_the_runtime_image_installs_tzdata():
    """python:3.12-slim has no /usr/share/zoneinfo: TZ=Europe/Berlin was ignored and logs showed UTC."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split("AS runtime", 1)[1]
    assert "tzdata" in runtime.split("rm -rf /var/lib/apt/lists/*", 1)[0]


@pytest.mark.parametrize("tz, missing", [
    ("Europe/Berlin", True),     # no file in the empty directory
    (":Europe/Berlin", True),
    ("UTC", False),
    ("Etc/UTC", False),
    ("CET-1CEST,M3.5.0,M10.5.0/3", False),  # a POSIX rule needs no zone file
])
def test_zone_file_missing(tmp_path, tz, missing):
    assert timezone_check.zone_file_missing(tz, tmp_path) is missing


def test_an_existing_zone_file_counts(tmp_path):
    (tmp_path / "Europe").mkdir()
    (tmp_path / "Europe" / "Berlin").write_bytes(b"TZif")
    assert timezone_check.zone_file_missing("Europe/Berlin", tmp_path) is False


def test_start_up_warns_when_tz_cannot_take_effect(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(timezone_check.os, "name", "posix")
    monkeypatch.setattr(timezone_check, "ZONEINFO_DIR", tmp_path)
    monkeypatch.setenv("TZ", "Europe/Berlin")
    monkeypatch.setattr(timezone_check, "zone_file_missing", lambda tz: True)
    with caplog.at_level(logging.INFO, logger="app.timezone_check"):
        timezone_check.log_timezone()
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "TZ=Europe/Berlin" in caplog.records[0].getMessage()


def test_start_up_names_the_zone_in_use(monkeypatch, caplog):
    monkeypatch.setattr(timezone_check.os, "name", "posix")
    monkeypatch.setenv("TZ", "UTC")
    with caplog.at_level(logging.INFO, logger="app.timezone_check"):
        timezone_check.log_timezone()
    assert caplog.records[0].levelno == logging.INFO
    assert caplog.records[0].getMessage().startswith("Time zone: UTC (")


def test_start_up_warns_when_tz_is_not_set(monkeypatch, caplog):
    """Without TZ the log only said "not set" at INFO, and times stayed UTC unnoticed."""
    monkeypatch.setattr(timezone_check.os, "name", "posix")
    monkeypatch.delenv("TZ", raising=False)
    with caplog.at_level(logging.INFO, logger="app.timezone_check"):
        timezone_check.log_timezone()
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "TZ=Europe/Berlin" in caplog.records[0].getMessage()
