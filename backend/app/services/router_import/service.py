"""Router import workflow: ask a router (preview), then add the picked networks (apply).

The preview writes nothing to the Subnet table. Apply adds new networks through
merge_subnets and only fills an existing row's empty gateway_ip/vlan_id; names and
values the admin set are never overwritten.
"""

from __future__ import annotations

import ipaddress
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.network import Subnet
from app.models.router_import import RouterImportSource
from app.schemas.network import MIN_SCAN_PREFIX, normalize_cidr
from app.schemas.router_import import (
    RouterImportApply,
    RouterImportApplyResult,
    RouterImportPreview,
    RouterImportRequest,
    RouterNetworkPreview,
    RouterSourceResponse,
)
from app.scanner.subnets import find_subnet, merge_subnets
from app.services import secret_vault
from app.services.router_import import PROVIDERS
from app.services.router_import.base import RouterConnection, RouterImportError, RouterNetwork, resolve_lan_target
from app.services.router_import.unifi import normalize_fingerprint
from app.services.secret_vault import VaultError

logger = logging.getLogger(__name__)


# --- saved connections -------------------------------------------------------

async def get_source(db: AsyncSession, provider: str) -> RouterImportSource | None:
    result = await db.execute(select(RouterImportSource).where(RouterImportSource.provider == provider))
    return result.scalar_one_or_none()


def _options(row: RouterImportSource) -> dict[str, str | None]:
    try:
        value = json.loads(row.options or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _secrets(row: RouterImportSource | None) -> dict[str, str]:
    if row is None or not row.encrypted_secrets:
        return {}
    try:
        value = json.loads(secret_vault.vault.decrypt(row.encrypted_secrets))
    except (VaultError, ValueError):
        logger.warning("Router import: stored credentials for '%s' cannot be decrypted; enter them again", row.provider)
        return {}
    return value if isinstance(value, dict) else {}


def source_view(row: RouterImportSource) -> RouterSourceResponse:
    return RouterSourceResponse(
        provider=row.provider, host=row.host, port=row.port, options=_options(row),
        stored_secrets=sorted(k for k, v in _secrets(row).items() if v),
    )


async def list_sources(db: AsyncSession) -> list[RouterSourceResponse]:
    rows = (await db.execute(select(RouterImportSource).order_by(RouterImportSource.provider))).scalars().all()
    return [source_view(row) for row in rows if row.provider in PROVIDERS]


async def delete_source(db: AsyncSession, provider: str) -> bool:
    row = await get_source(db, provider)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


def _same_router(row: RouterImportSource | None, host: str) -> bool:
    return row is not None and row.host.strip().lower() == host.strip().lower()


async def _remember(db: AsyncSession, row: RouterImportSource | None, req: RouterImportRequest,
                    options: dict[str, str | None], secrets: dict[str, str]) -> None:
    if row is None:
        row = RouterImportSource(provider=req.provider, host=req.host.strip())
        db.add(row)
    row.host = req.host.strip()
    row.port = req.port
    row.options = json.dumps(options)
    stored = {k: v for k, v in secrets.items() if v}
    row.encrypted_secrets = secret_vault.vault.encrypt(json.dumps(stored)) if stored else None
    await db.commit()


# --- preview -----------------------------------------------------------------

def _clean_options(provider: str, options: dict[str, str | None]) -> dict[str, str | None]:
    allowed = PROVIDERS[provider].option_fields
    cleaned = {k: (v.strip() if isinstance(v, str) else v) for k, v in options.items() if k in allowed}
    if "fingerprint" in cleaned:
        cleaned["fingerprint"] = normalize_fingerprint(cleaned["fingerprint"])
    return {k: v for k, v in cleaned.items() if v}


async def preview(db: AsyncSession, req: RouterImportRequest) -> RouterImportPreview:
    """Ask the router and compare its networks with the Subnet table. Writes no subnets."""
    provider = PROVIDERS[req.provider]()
    options = _clean_options(req.provider, req.options)
    address = await resolve_lan_target(req.host)

    row = await get_source(db, req.provider)
    stored = _secrets(row) if _same_router(row, req.host) else {}
    secrets = {f: (req.secrets.get(f) or stored.get(f) or "") for f in provider.secret_fields}

    conn = RouterConnection(host=req.host.strip(), address=address, port=req.port, options=options, secrets=secrets)
    try:
        networks = await provider.fetch(conn)
    except RouterImportError as err:
        if err.detail.get("fingerprint"):
            return RouterImportPreview(
                status="confirm_certificate", provider=req.provider, host=conn.host,
                fingerprint=err.detail["fingerprint"], reason=err.detail.get("reason"), message=err.message,
            )
        raise
    logger.info("Router import: %s at %s reported %d network(s)", req.provider, conn.host, len(networks))
    if req.remember:
        await _remember(db, row, req, options, secrets)
    return RouterImportPreview(
        status="ok", provider=req.provider, host=conn.host, networks=await _compare(db, networks),
    )


async def _subnets_by_cidr(db: AsyncSession) -> dict[str, Subnet]:
    by_cidr: dict[str, Subnet] = {}
    for row in (await db.execute(select(Subnet).order_by(Subnet.id))).scalars().all():
        try:
            by_cidr.setdefault(normalize_cidr(row.cidr), row)
        except ValueError:
            continue
    return by_cidr


def _fills(row: Subnet, gateway_ip: str | None, vlan_id: int | None) -> list[str]:
    """Which of the row's empty fields the router can fill in (a gateway must lie inside the subnet)."""
    fills = []
    if not row.gateway_ip and gateway_ip and ipaddress.ip_address(gateway_ip) in ipaddress.ip_network(row.cidr, strict=False):
        fills.append("gateway_ip")
    if row.vlan_id is None and vlan_id is not None:
        fills.append("vlan_id")
    return fills


async def _compare(db: AsyncSession, networks: list[RouterNetwork]) -> list[RouterNetworkPreview]:
    existing = await _subnets_by_cidr(db)
    result = []
    for net in networks:
        try:
            cidr = normalize_cidr(net.cidr)
        except ValueError:
            continue
        name = (net.name or "").strip()[:100] or None
        item = RouterNetworkPreview(
            cidr=cidr, name=name, gateway_ip=net.gateway_ip, vlan_id=net.vlan_id, interface=net.interface, status="new",
        )
        row = existing.get(cidr)
        if ipaddress.ip_network(cidr).prefixlen < MIN_SCAN_PREFIX:
            item.status = "too_large"
        elif row is not None:
            item.existing_name = row.name
            item.fills = _fills(row, net.gateway_ip, net.vlan_id)
            item.status = "update" if item.fills else "exists"
        result.append(item)
    return result


# --- apply -------------------------------------------------------------------

async def apply(db: AsyncSession, req: RouterImportApply) -> RouterImportApplyResult:
    """Add the picked networks; for configured ones only fill an empty gateway/VLAN."""
    result = RouterImportApplyResult()
    for item in req.networks:
        row = await find_subnet(db, item.cidr)
        if row is None:
            name = (item.name or "").strip()
            await merge_subnets(db, [item.cidr], names={item.cidr: name} if name else None)
            row = await find_subnet(db, item.cidr)
            if row is None:  # pragma: no cover - merge_subnets accepted the validated CIDR
                continue
            row.gateway_ip = item.gateway_ip
            row.vlan_id = item.vlan_id
            result.added.append(item.cidr)
            continue
        fills = _fills(row, item.gateway_ip, item.vlan_id)
        if "gateway_ip" in fills:
            row.gateway_ip = item.gateway_ip
        if "vlan_id" in fills:
            row.vlan_id = item.vlan_id
        (result.updated if fills else result.unchanged).append(item.cidr)
    await db.commit()
    return result
