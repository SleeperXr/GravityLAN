"""Notification texts and per-service requests are the same as before the webhook_service refactor.

Frozen copies (0.7.0-rc.7) of format_event_notification and prepare_request_for_service run next to the live
functions over every event type and alias, unknown events, sparse and full data, every service preset,
Gotify URLs with and without /message, with and without a token.
"""

import itertools
import json
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import pytest

import app.services.webhook_service as ws


def _old_format(event_type, data):
    alias_key = event_type
    for canonical, aliases in ws.EVENT_ALIASES.items():
        if event_type in aliases:
            alias_key = canonical
            break
    if alias_key in ("device.offline", "offline"):
        dev_name = data.get("display_name") or data.get("hostname") or data.get("ip") or "Device"
        return ("GravityLAN: Device Offline", f"Device '{dev_name}' ({data.get('ip', 'unknown')}) is offline", 8, ["warning", "skull"])
    if alias_key in ("device.online", "online"):
        dev_name = data.get("display_name") or data.get("hostname") or data.get("ip") or "Device"
        return ("GravityLAN: Device Online", f"Device '{dev_name}' ({data.get('ip', 'unknown')}) is back online", 5, ["white_check_mark"])
    if alias_key in ("new_device", "device.new"):
        dev_name = data.get("hostname") or data.get("vendor") or data.get("ip") or "New device"
        ip = data.get("ip", "unknown")
        mac = data.get("mac") or "N/A"
        return ("GravityLAN: New Device Discovered", f"New device discovered: {dev_name} (IP: {ip}, MAC: {mac})", 5, ["sparkles", "computer"])
    if alias_key in ("device.ip_changed", "ip_changed"):
        dev_name = data.get("display_name") or data.get("hostname") or "Device"
        return ("GravityLAN: IP Address Changed",
                f"Device '{dev_name}' changed IP from {data.get('old_ip', 'unknown')} to {data.get('new_ip', 'unknown')}", 5, ["satellite"])
    if alias_key == "scan.complete":
        return ("GravityLAN: Scan Complete", f"Network discovery scan complete: {data.get('hosts_found', 0)} hosts found", 3, ["mag"])
    if alias_key == "test.event":
        dest = data.get("destination") or "endpoint"
        return ("GravityLAN: Test Notification", f"Test notification for {dest} delivered successfully.", 5, ["white_check_mark", "bell"])
    return (f"GravityLAN: {event_type}", json.dumps(data, ensure_ascii=False), 5, ["bell"])


def _old_prepare(service_type, url, token, event_type, data, now):
    title, message, prio, tags = _old_format(event_type, data)
    if service_type == "ntfy":
        ntfy_prio = "high" if prio >= 8 else ("low" if prio <= 3 else "default")
        headers = {"Title": title, "Priority": ntfy_prio, "Tags": ",".join(tags), "Content-Type": "text/plain; charset=utf-8"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return url, headers, message.encode("utf-8")
    if service_type == "gotify":
        parsed = urlparse(url)
        eff_url = url
        if not parsed.path.rstrip("/").endswith("/message"):
            eff_url = urlunparse(parsed._replace(path=parsed.path.rstrip("/") + "/message"))
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Gotify-Key"] = token
        return eff_url, headers, {"title": title, "message": message, "priority": prio}
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return url, headers, {"event": event_type, "timestamp": now.isoformat(), "data": data}


EVENTS = sorted({e for aliases in ws.EVENT_ALIASES.values() for e in aliases} | set(ws.EVENT_ALIASES)
                | {"offline", "online", "new_device", "device.new", "ip_changed", "scan.complete", "test.event", "custom.thing", ""})
DATA = [
    {},
    {"ip": "10.0.0.5"},
    {"display_name": "NAS", "hostname": "nas.lan", "ip": "10.0.0.5", "mac": "aa:bb", "vendor": "Synology",
     "old_ip": "10.0.0.4", "new_ip": "10.0.0.5", "hosts_found": 12, "destination": "ntfy"},
    {"hostname": "", "vendor": "Ubiquiti", "display_name": None, "mac": "", "destination": "", "note": "Grüße"},
]
URLS = ["https://ntfy.sh/topic", "https://gotify.lan", "https://gotify.lan/", "https://gotify.lan/message",
        "https://gotify.lan/sub/message/", "http://hook.lan/x?y=1"]


def test_notification_texts_match_for_every_event_and_data():
    for event, data in itertools.product(EVENTS, DATA):
        assert ws.format_event_notification(event, data) == _old_format(event, data), event


@pytest.mark.parametrize("service", ["ntfy", "gotify", "webhook", "generic", "unknown"])
def test_requests_match_for_every_service_url_and_token(service, monkeypatch):
    now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)

    class FrozenNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(ws, "datetime", FrozenNow)
    for url, token, event, data in itertools.product(URLS, [None, "", "tok"], EVENTS[:6] + ["custom.thing"], DATA):
        assert ws.prepare_request_for_service(service, url, token, event, data) == _old_prepare(service, url, token, event, data, now)
