"""Router import from a UniFi console (Cloud Gateway, UDM, UXG) over the official local API.

Uses the UniFi Network Integration API (developer.ui.com, "Network" section) with an
API key from UniFi Network > Settings > Control Plane > Integrations:

  GET /proxy/network/integration/v1/sites                         -> site id
  GET /proxy/network/integration/v1/sites/{siteId}/networks       -> id, name, vlanId, enabled
  GET /proxy/network/integration/v1/sites/{siteId}/networks/{id}  -> ipv4Configuration
                                                                     (hostIpAddress, prefixLength)

Consoles ship a self-signed certificate, so instead of skipping verification the
certificate is pinned by its SHA-256 fingerprint: the check runs right after the
TLS handshake, before the request (and with it the API key) is sent. Without a
pinned fingerprint the fetch stops there and reports the fingerprint for the admin
to confirm.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import ssl
from typing import Any

import httpx

from app.services.router_import.base import RouterConnection, RouterImportError, RouterNetwork, RouterProvider

logger = logging.getLogger(__name__)

API_PREFIX = "/proxy/network/integration/v1"
PAGE_LIMIT = 200
MAX_PAGES = 50
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def normalize_fingerprint(value: str | None) -> str | None:
    """A SHA-256 fingerprint as AA:BB:..., or None when empty; RouterImportError when malformed."""
    if not value or not value.strip():
        return None
    compact = re.sub(r"[\s:-]", "", value.strip().lower())
    if compact.startswith("sha256"):
        compact = compact[6:].lstrip("=")
    if not _HEX64.match(compact):
        raise RouterImportError("The certificate fingerprint must be a SHA-256 hash (64 hex digits).", 400)
    return ":".join(compact[i:i + 2] for i in range(0, 64, 2)).upper()


def certificate_fingerprint(der: bytes) -> str:
    digest = hashlib.sha256(der).hexdigest()
    return ":".join(digest[i:i + 2] for i in range(0, 64, 2)).upper()


class CertificatePin:
    """Checks the console's certificate after each TLS handshake, before any request is sent."""

    def __init__(self, host: str, pinned: str | None):
        self.host = host
        self.pinned = pinned

    async def trace(self, event: str, info: dict[str, Any]) -> None:
        """httpcore trace hook; raising here aborts the connection before the request is written."""
        if event != "connection.start_tls.complete":
            return
        stream = info.get("return_value")
        ssl_object = stream.get_extra_info("ssl_object") if stream is not None else None
        der = ssl_object.getpeercert(binary_form=True) if ssl_object is not None else None
        if not der:
            raise RouterImportError(f"{self.host} did not present a TLS certificate.", 502)
        self.check(der)

    def check(self, der: bytes) -> None:
        presented = certificate_fingerprint(der)
        if self.pinned is None:
            raise RouterImportError(
                "Confirm the console's certificate fingerprint to continue. Compare it with the one "
                "your browser shows for the console (certificate details, SHA-256).",
                409,
                {"fingerprint": presented, "reason": "untrusted_certificate"},
            )
        if presented != self.pinned:
            raise RouterImportError(
                "The console presented a different certificate than the pinned one. If it was renewed, "
                "confirm the new fingerprint; otherwise someone may be intercepting the connection.",
                409,
                {"fingerprint": presented, "reason": "certificate_mismatch"},
            )


def networks_from_detail(detail: dict[str, Any]) -> list[RouterNetwork]:
    """The networks (gateway address + prefix) one UniFi network detail describes."""
    ipv4 = detail.get("ipv4Configuration") or {}
    name = (detail.get("name") or "").strip() or None
    vlan = detail.get("vlanId")
    vlan_id = vlan if isinstance(vlan, int) and 1 <= vlan <= 4094 else None
    entries = []
    host, prefix = ipv4.get("hostIpAddress"), ipv4.get("prefixLength")
    if host and isinstance(prefix, int):
        entries.append(f"{host}/{prefix}")
    entries.extend(s for s in ipv4.get("additionalHostIpSubnets") or [] if isinstance(s, str))
    networks = []
    for entry in entries:
        try:
            iface = ipaddress.IPv4Interface(entry.strip())
        except ValueError:
            logger.debug("Router import: UniFi network '%s' has an unusable subnet '%s'", name, entry)
            continue
        networks.append(RouterNetwork(
            cidr=str(iface.network), gateway_ip=str(iface.ip), name=name, vlan_id=vlan_id,
        ))
    return networks


def pick_site(sites: list[dict[str, Any]], wanted: str | None) -> dict[str, Any]:
    """The site to import from: the one named in ``wanted``, the only one, or 'default'."""
    if not sites:
        raise RouterImportError("The console reports no UniFi Network site.", 502)
    if wanted and wanted.strip():
        key = wanted.strip().lower()
        for site in sites:
            if key in {str(site.get(f) or "").lower() for f in ("id", "internalReference", "name")}:
                return site
        raise RouterImportError(f"Site '{wanted.strip()}' not found. Sites: {_site_names(sites)}.", 400)
    if len(sites) == 1:
        return sites[0]
    for site in sites:
        if site.get("internalReference") == "default":
            return site
    raise RouterImportError(f"The console has several sites; enter one of: {_site_names(sites)}.", 400)


def _site_names(sites: list[dict[str, Any]]) -> str:
    return ", ".join(str(s.get("name") or s.get("internalReference") or s.get("id")) for s in sites)


class UnifiProvider(RouterProvider):
    key = "unifi"
    default_port = 443
    secret_fields = ("api_key",)
    option_fields = ("site", "fingerprint")

    def make_client(self, conn: RouterConnection) -> httpx.AsyncClient:
        """HTTPS client to the console; certificate trust comes from CertificatePin, not from a CA."""
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        address = conn.address if ":" not in conn.address else f"[{conn.address}]"
        return httpx.AsyncClient(
            base_url=f"https://{address}:{conn.port or self.default_port}",
            verify=context,
            timeout=10.0,
            follow_redirects=False,
        )

    async def fetch(self, conn: RouterConnection) -> list[RouterNetwork]:
        api_key = (conn.secrets.get("api_key") or "").strip()
        if not api_key:
            raise RouterImportError("Enter the UniFi API key.", 400)
        pin = CertificatePin(conn.host, normalize_fingerprint(conn.options.get("fingerprint")))
        headers = {"X-API-KEY": api_key, "Accept": "application/json"}

        async with self.make_client(conn) as client:
            async def get(path: str, params: dict[str, Any] | None = None) -> Any:
                return await self._get_json(client, conn.host, path, headers, pin, params)

            sites = await self._get_all(get, f"{API_PREFIX}/sites")
            site_id = pick_site(sites, conn.options.get("site")).get("id")
            overview = await self._get_all(get, f"{API_PREFIX}/sites/{site_id}/networks")
            networks: list[RouterNetwork] = []
            for net in overview:
                if net.get("enabled") is False or not net.get("id"):
                    continue
                detail = await get(f"{API_PREFIX}/sites/{site_id}/networks/{net['id']}")
                if isinstance(detail, dict):
                    networks.extend(networks_from_detail(detail))
            return networks

    @staticmethod
    async def _get_all(get, path: str) -> list[dict[str, Any]]:
        """Every item of a paginated list endpoint (offset/limit/totalCount)."""
        items: list[dict[str, Any]] = []
        offset = 0
        for _ in range(MAX_PAGES):
            page = await get(path, {"offset": offset, "limit": PAGE_LIMIT})
            data = page.get("data") if isinstance(page, dict) else None
            if not isinstance(data, list):
                raise RouterImportError("The console sent an unexpected answer (no 'data' list).", 502)
            items.extend(d for d in data if isinstance(d, dict))
            offset += len(data)
            total = page.get("totalCount")
            if not data or not isinstance(total, int) or offset >= total:
                break
        return items

    @staticmethod
    async def _get_json(client: httpx.AsyncClient, host: str, path: str, headers: dict[str, str],
                        pin: CertificatePin, params: dict[str, Any] | None = None) -> Any:
        try:
            response = await client.get(path, params=params, headers=headers, extensions={"trace": pin.trace})
        except RouterImportError:
            raise
        except httpx.TimeoutException:
            raise RouterImportError(f"{host} did not answer in time.", 502) from None
        except httpx.HTTPError as err:
            raise RouterImportError(f"Could not connect to {host} over HTTPS: {type(err).__name__}.", 502) from None
        status = response.status_code
        if status in (401, 403):
            raise RouterImportError(
                "The console rejected the API key. Create one under UniFi Network > Settings > Control Plane > Integrations.",
                502,
            )
        if status == 404:
            raise RouterImportError(
                "The console does not offer this part of the UniFi Network Integration API "
                "(UniFi OS console with a current UniFi Network version needed).",
                502,
            )
        if 300 <= status < 400:
            raise RouterImportError(f"{host} redirected the request; is this the address of a UniFi OS console?", 502)
        if status >= 400:
            raise RouterImportError(f"The console answered with HTTP {status}.", 502)
        try:
            return response.json()
        except ValueError:
            raise RouterImportError("The console sent an answer that is not JSON.", 502) from None
