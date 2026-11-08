"""
Vendor lookup module using OUI-based identification and local caching.
Supports static fallbacks, local file cache, and online API lookup.
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

from app.config import process_ids, settings

# Standard Logger setup
logger = logging.getLogger(__name__)

# -- Global State for Rate Limiting & Throttling -----------------------------
_last_429_time: float = 0.0
_COOLDOWN_SECONDS: int = 300  # 5 minutes
_last_api_request_time: float = 0.0
_MIN_API_INTERVAL: float = 1.2  # api.macvendors.com allows max 1 req/sec
_api_lock = threading.Lock()

# -- Configuration -----------------------------------------------------------
_DATA_DIR = os.path.join(settings.data_dir, "cache")
CACHE_FILE = os.path.join(_DATA_DIR, "mac_cache.json")
_permission_warned: bool = False

# -- Static Fallback Database (Common HomeLab Vendors) -----------------------
COMMON_VENDORS = {
    "00:11:32": "Synology Inc.",
    "00:15:5D": "Microsoft Corporation (Hyper-V)",
    "08:00:27": "Oracle Corporation (VirtualBox)",
    "00:0C:29": "VMware, Inc.",
    "00:50:56": "VMware, Inc.",
    "B8:27:EB": "Raspberry Pi Foundation",
    "DC:A6:32": "Raspberry Pi Foundation",
    "E4:5F:01": "Raspberry Pi Foundation",
    "74:83:C2": "Ubiquiti Networks",
    "FC:EC:DA": "Ubiquiti Networks",
    "00:15:6D": "Ubiquiti Networks",
    "AC:86:74": "Apple, Inc.",
    "D8:49:2F": "Apple, Inc.",
    "00:01:C0": "CompuLab",
    "00:22:6B": "Cisco Systems",
    "00:E0:4C": "Realtek Semiconductor Corp.",
    "00:16:3E": "Xensource, Inc. (Xen)",
    "52:54:00": "QEMU/KVM Virtual Machine",
}

# -- Module-level state ------------------------------------------------------
_vendor_cache: dict[str, str] = {}
_cache_loaded: bool = False
_cache_lock = threading.Lock()


def is_locally_administered_mac(mac: str) -> bool:
    """
    Checks if a MAC address has the locally administered address (LAA) bit set.
    According to IEEE 802, bit 1 of byte 0 indicates private/randomized MACs
    (e.g., modern mobile devices or virtual interfaces). These do not have public IEEE OUIs.
    """
    clean = mac.replace("-", ":").split(":")
    if not clean or len(clean[0]) < 2:
        return False
    try:
        first_byte = int(clean[0], 16)
        return bool(first_byte & 0x02)
    except ValueError:
        return False


def _load_cache() -> None:
    """
    Loads the vendor cache from the local JSON file.
    Uses a thread lock to ensure thread safety during initialization.
    """
    global _vendor_cache, _cache_loaded
    if _cache_loaded:
        return

    with _cache_lock:
        if _cache_loaded:  # Double-check pattern
            return

        if not os.path.exists(CACHE_FILE):
            _cache_loaded = True
            return

        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _vendor_cache = json.load(f)
            logger.debug(f"Loaded {len(_vendor_cache)} vendors from cache.")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse vendor cache file {CACHE_FILE}: {e}")
            _vendor_cache = {}
        except OSError as e:
            logger.error(f"Failed to read vendor cache file {CACHE_FILE}: {e}")
            _vendor_cache = {}
        finally:
            _cache_loaded = True


def _save_cache() -> None:
    """
    Saves the current module-level vendor cache to the local JSON file.
    This is intended to be run in a separate thread.
    """
    global _permission_warned
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        with _cache_lock:
            cache_snapshot = dict(_vendor_cache)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_snapshot, f, ensure_ascii=False, indent=2)
        _permission_warned = False
    except PermissionError as e:
        if not _permission_warned:
            uid, gid = process_ids()
            logger.warning(
                f"Failed to persist vendor cache to {CACHE_FILE}: {e}. "
                f"Ensure UID {uid} / GID {gid} can write to the data volume "
                f"(e.g., run 'sudo chown -R {uid}:{gid} ./data' on the host). "
                "In-memory caching remains active."
            )
            _permission_warned = True
    except OSError as e:
        logger.warning(f"Failed to persist vendor cache to {CACHE_FILE}: {e}")


def _extract_oui(mac: str | None) -> str | None:
    """Extracts and normalizes the 8-character OUI prefix from a MAC address."""
    if not mac or mac == "-" or "N/A" in mac.upper():
        return None

    mac_normalized = mac.replace("-", ":").upper()
    if len(mac_normalized) < 8:
        return None

    return mac_normalized[:8]


def _get_cached_vendor(oui: str) -> str | None:
    """Retrieves vendor from cache if loaded, returning None if not found."""
    _load_cache()
    with _cache_lock:
        return _vendor_cache.get(oui)


def _cache_vendor(oui: str, vendor: str) -> None:
    """Stores vendor in memory and persists to disk in a background thread."""
    with _cache_lock:
        _vendor_cache[oui] = vendor
    threading.Thread(target=_save_cache, daemon=True).start()


def get_vendor(mac: str | None, use_cache: bool = True) -> str:
    """
    Identifies the hardware vendor based on the MAC address OUI.

    Args:
        mac: The MAC address to look up.
        use_cache: Whether to use and update the local file cache.

    Returns:
        The vendor name as a string, or an empty string if not identified.
    """
    oui = _extract_oui(mac)
    if not oui:
        return ""

    # 1. Check static fallback (Fastest)
    if oui in COMMON_VENDORS:
        return COMMON_VENDORS[oui]

    # 2. Check local cache (includes negative hits where value is "")
    if use_cache:
        cached = _get_cached_vendor(oui)
        if cached is not None:
            return cached

    # 3. API Lookup (Last resort)
    mac_normalized = mac.replace("-", ":").upper() if mac else ""
    vendor = _api_lookup(mac_normalized)

    if use_cache:
        _cache_vendor(oui, vendor)

    return vendor


def _check_and_update_rate_limit() -> bool:
    """
    Verifies API cooldown and enforces the minimum inter-request interval.
    Returns True if rate-limited (should abort), False if allowed to proceed.
    Must be called while holding _api_lock.
    """
    global _last_api_request_time
    now = time.time()

    if now - _last_429_time < _COOLDOWN_SECONDS:
        return True

    elapsed = now - _last_api_request_time
    if elapsed < _MIN_API_INTERVAL:
        time.sleep(_MIN_API_INTERVAL - elapsed)

    _last_api_request_time = time.time()
    return False


def _handle_rate_limit_exceeded(detail: str = "") -> None:
    """Sets the 429 cooldown timestamp and logs a warning."""
    global _last_429_time
    _last_429_time = time.time()
    msg = f" ({detail})" if detail else ""
    logger.warning(
        f"API rate limit hit{msg}. Entering {_COOLDOWN_SECONDS // 60}m cooldown."
    )


def _parse_api_response(response_text: str) -> str:
    """Parses vendor name from API response, filtering error messages."""
    vendor = response_text.strip()
    if vendor and "errors" not in vendor.lower() and "not found" not in vendor.lower():
        return vendor
    return ""


def _fetch_vendor_from_api(mac_query: str) -> str:
    """Executes the HTTP GET to the vendor API and handles protocol errors."""
    url = f"https://api.macvendors.com/{mac_query}"
    headers = {
        "User-Agent": "GravityLAN/1.1 (github.com/SleeperXr/GravityLAN)",
        "Accept": "text/plain",
    }
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                body = response.read().decode("utf-8", errors="replace")
                return _parse_api_response(body)
            if response.status == 429:
                _handle_rate_limit_exceeded()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _handle_rate_limit_exceeded(f"HTTP {e.code}")
        elif e.code != 404:  # 404 is "Not Found", which is expected for unknown OUIs
            logger.debug("API vendor lookup HTTP error: %d", e.code)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        logger.debug("API vendor lookup network failure: %s", e)
    except Exception as e:
        logger.debug("API vendor lookup unexpected failure: %s", e)

    return ""


def _api_lookup(mac: str) -> str:
    """
    Fallback API lookup for unknown OUIs using native urllib.
    Adheres strictly to rate limits (max 1 req/s) and respects 429 cooldowns.

    Args:
        mac: The normalized MAC address.

    Returns:
        The vendor name if found, else an empty string.
    """
    with _api_lock:
        if _check_and_update_rate_limit():
            return ""

        # Use only the first 6 hex chars (3 bytes) for the API
        mac_query = mac.replace(":", "").replace("-", "")[:6]
        return _fetch_vendor_from_api(mac_query)
