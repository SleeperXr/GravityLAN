import json
import os
import threading
import logging
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# -- Project-specific cache --------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_BASE_DIR, "data", "cache")
os.makedirs(_DATA_DIR, exist_ok=True)
CACHE_FILE = os.path.join(_DATA_DIR, "mac_cache.json")

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
_vendor_cache: Dict[str, str] = {}
_cache_loaded: bool = False

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

    # 1. Check static fallback (Fastest)
    if oui in COMMON_VENDORS:
        return COMMON_VENDORS[oui]

    # 2. Check local cache
    if use_cache:
        _load_cache()
        if oui in _vendor_cache:
            return _vendor_cache[oui]

    # 3. API Lookup (Last resort)
    vendor = _api_lookup(mac_normalized)

    if vendor:
        if use_cache:
            _vendor_cache[oui] = vendor
            threading.Thread(target=_save_cache, daemon=True).start()
        return vendor

    return ""

def _api_lookup(mac: str) -> str:
    """Fallback API lookup for unknown OUIs using native urllib (no curl dependency)."""
    try:
        mac_query = mac.replace(":", "").replace("-", "")[:6]
        url = f"https://api.macvendors.com/{mac_query}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GravityLAN/1.0",
            "Accept": "text/plain"
        }
        
        req = urllib.request.Request(url, headers=headers)
        # Using native urllib to avoid 'curl' dependency in minimal environments/Docker
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                vendor = response.read().decode('utf-8').strip()
                if vendor and "errors" not in vendor.lower() and "not found" not in vendor.lower():
                    return vendor
    except Exception as e:
        # Rate limiting or network issues are common with this API
        logger.debug(f"API vendor lookup failed for {mac}: {e}")

    return ""
