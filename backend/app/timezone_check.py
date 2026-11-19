"""Say at start-up which time zone the log uses, and warn when TZ is missing or cannot take effect.

Log times come from the C library (time.localtime). It reads TZ only when the zone file exists
under /usr/share/zoneinfo; without it TZ=Europe/Berlin is silently ignored and every log time is
UTC. The image installs tzdata for that, so the warning points at a broken or custom image.
"""
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

ZONEINFO_DIR = Path("/usr/share/zoneinfo")
_UTC_NAMES = {"", "UTC", "UTC0", "GMT", "GMT0", "ETC/UTC", "ZULU"}
# A POSIX TZ rule starts with an abbreviation and an offset ("CET-1CEST,..."); a zone name does not
_POSIX_RULE = re.compile(r"^(<[^>]+>|[A-Za-z]{3,})[+-]?\d")


def _offset() -> str:
    """The current UTC offset as +HH:MM."""
    seconds = -(time.altzone if time.localtime().tm_isdst > 0 else time.timezone)
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    return f"{sign}{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def zone_file_missing(tz: str, zoneinfo_dir: Path = ZONEINFO_DIR) -> bool:
    """True when TZ names a zone (like Europe/Berlin) whose file is missing, so it is ignored."""
    name = tz.strip().lstrip(":")
    if name.upper() in _UTC_NAMES or "/" not in name or _POSIX_RULE.match(name):
        return False  # UTC, or a POSIX rule such as CET-1CEST,M3.5.0,M10.5.0/3: needs no zone file
    return not (zoneinfo_dir / name).is_file()


def log_timezone() -> None:
    """One line with the zone the log uses; a warning when TZ is not set or has no effect."""
    if os.name != "posix":
        return
    tz = os.environ.get("TZ", "")
    if not tz.strip():
        logger.warning(
            "TZ is not set, so log times are UTC. Set the TZ environment variable "
            "of the container to your zone, for example TZ=Europe/Berlin (TZ=UTC keeps UTC and "
            "silences this warning).")
        return
    if tz and zone_file_missing(tz):
        logger.warning(
            "TZ=%s is set, but %s is missing, so it has no effect and log times are UTC. "
            "The image needs the tzdata package.", tz, ZONEINFO_DIR / tz.strip().lstrip(":"))
        return
    logger.info("Time zone: %s (%s, UTC%s)", tz or "not set", time.strftime("%Z"), _offset())
