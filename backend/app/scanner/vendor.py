import json
import os
import subprocess
import threading
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple

# -- Project-specific cache --------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_BASE_DIR, "data", "cache")
os.makedirs(_DATA_DIR, exist_ok=True)
CACHE_FILE = os.path.join(_DATA_DIR, "mac_cache.json")

# -- Module-level state ------------------------------------------------------
_vendor_cache: Dict[str, str] = {}
_cache_loaded: bool = False
_api_available: Optional[bool] = None

def _load_cache() -> None:
    global _vendor_cache, _cache_loaded
    if _cache_loaded:
        return
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _vendor_cache = json.load(f)
    except Exception:
        _vendor_cache = {}
    _cache_loaded = True

def _save_cache() -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_vendor_cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_vendor(mac: str, use_cache: bool = True) -> str:
    if not mac or mac == "-" or "N/A" in mac.upper():
        return ""

    mac_normalized = mac.replace("-", ":").upper()
    if len(mac_normalized) < 8:
        return ""

    oui = mac_normalized[:8]

    if use_cache:
        _load_cache()
        if oui in _vendor_cache:
            return _vendor_cache[oui]

    vendor = _api_lookup(mac_normalized)

    if use_cache and vendor:
        _vendor_cache[oui] = vendor
        threading.Thread(target=_save_cache, daemon=True).start()

    return vendor

def _api_lookup(mac: str) -> str:
    global _api_available
    try:
        mac_query = mac.replace(":", "").replace("-", "")[:6]
        url = f"https://api.macvendors.com/{mac_query}"

        cmd = [
            "curl", "-s", "-m", "2",
            "-H", "Accept: text/plain",
            "-A", "GravityLAN/1.0",
            url
        ]

        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )

        if res.returncode == 0:
            vendor = res.stdout.strip()
            if vendor and "errors" not in vendor.lower() and "not found" not in vendor.lower():
                _api_available = True
                return vendor
    except Exception:
        _api_available = False

    return ""
