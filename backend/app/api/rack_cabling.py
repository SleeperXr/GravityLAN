"""Rack equipment (switches, UPS, patch panels, blanks, ...), their ports, and the cables between ports.

Placement is checked here, not only in the browser: a rack item may not cover a unit that a network device or
another rack item already covers. A port carries at most one cable, and a cable joins two different owners.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.device import Device as DeviceModel
from app.models.rack_cabling import RackCable, RackItem, RackPort
from app.models.topology import Rack
from app.schemas.rack_cabling import CableIn, CableOut, CablePatch, CablingOut, PortOut, PortsIn, RackItemIn, RackItemOut, RackItemPatch

router = APIRouter(prefix="/api/topology", tags=["rack-cabling"])

# Columns a rack item cannot be saved without
REQUIRED_ITEM_FIELDS = ("rack_id", "name", "kind", "rack_height")


def _span(unit: int, height: int) -> set[int]:
    """The units a thing at `unit` (its top unit) covering `height` units downwards takes."""
    return set(range(unit - height + 1, unit + 1))


async def _check_placement(db: AsyncSession, rack_id: int, unit: int | None, height: int, *, exclude_item_id: int | None = None) -> None:
    rack = await db.get(Rack, rack_id)
    if rack is None:
        raise HTTPException(status_code=404, detail="Rack not found")
    if unit is None:
        return
    span = _span(unit, height)
    if min(span) < 1 or max(span) > rack.units:
        raise HTTPException(status_code=422, detail="The item does not fit inside the rack")
    devices = (
        await db.execute(select(DeviceModel).where(DeviceModel.rack_id == rack_id, DeviceModel.rack_unit.is_not(None)))
    ).scalars().all()
    for device in devices:
        if _span(device.rack_unit, device.rack_height or 1) & span:
            raise HTTPException(status_code=409, detail=f"Unit already taken by {device.display_name or device.ip}")
    items = (await db.execute(select(RackItem).where(RackItem.rack_id == rack_id, RackItem.rack_unit.is_not(None)))).scalars().all()
    for item in items:
        if item.id != exclude_item_id and _span(item.rack_unit, item.rack_height) & span:
            raise HTTPException(status_code=409, detail=f"Unit already taken by {item.name}")


async def _cabled_port_ids(db: AsyncSession, port_ids: list[int]) -> set[int]:
    """Which of `port_ids` already has a cable at one of its ends."""
    if not port_ids:
        return set()
    rows = (
        await db.execute(
            select(RackCable.a_port_id, RackCable.b_port_id).where(
                or_(RackCable.a_port_id.in_(port_ids), RackCable.b_port_id.in_(port_ids))
            )
        )
    ).all()
    return {port for row in rows for port in row if port in port_ids}


async def _set_ports(db: AsyncSession, owner_field: str, owner_id: int, count: int, kind: str, side: str) -> None:
    """Give the owner exactly ports 1..count, all of `kind`. A port that still has a cable cannot be removed."""
    column = getattr(RackPort, owner_field)
    existing = (await db.execute(select(RackPort).where(column == owner_id))).scalars().all()
    removed = [port.id for port in existing if port.number > count]
    if await _cabled_port_ids(db, removed):
        raise HTTPException(status_code=409, detail="A port that would be removed still has a cable")
    numbers = {port.number for port in existing}
    for port in existing:
        if port.number > count:
            await db.delete(port)
        else:
            port.kind = kind
            port.side = side
    for number in range(1, count + 1):
        if number not in numbers:
            db.add(RackPort(**{owner_field: owner_id}, number=number, kind=kind, side=side))


@router.get("/cabling", response_model=CablingOut)
async def get_cabling(db: AsyncSession = Depends(get_db)):
    """Rack items, every port and every cable: what the rack view needs in one request."""
    items = (await db.execute(select(RackItem))).scalars().all()
    ports = (await db.execute(select(RackPort))).scalars().all()
    cables = (await db.execute(select(RackCable))).scalars().all()
    return {"items": items, "ports": ports, "cables": cables}


@router.post("/rack-items", response_model=RackItemOut)
async def create_rack_item(data: RackItemIn, db: AsyncSession = Depends(get_db)):
    await _check_placement(db, data.rack_id, data.rack_unit, data.rack_height)
    item = RackItem(
        rack_id=data.rack_id,
        name=data.name,
        kind=data.kind,
        rack_unit=data.rack_unit,
        rack_height=data.rack_height,
        notes=data.notes,
    )
    db.add(item)
    await db.flush()
    await _set_ports(db, "rack_item_id", item.id, data.port_count, data.port_kind, "front")
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/rack-items/{item_id}", response_model=RackItemOut)
async def update_rack_item(item_id: int, patch: RackItemPatch, db: AsyncSession = Depends(get_db)):
    item = await db.get(RackItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Rack item not found")
    values = patch.model_dump(exclude_unset=True)
    if any(field in values and values[field] is None for field in REQUIRED_ITEM_FIELDS):
        raise HTTPException(status_code=422, detail="This field cannot be cleared")
    await _check_placement(
        db,
        values.get("rack_id", item.rack_id),
        values.get("rack_unit", item.rack_unit),
        values.get("rack_height", item.rack_height),
        exclude_item_id=item.id,
    )
    for field, value in values.items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/rack-items/{item_id}")
async def delete_rack_item(item_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(RackItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Rack item not found")
    # Explicit, so the cleanup does not depend on the database enforcing foreign keys
    port_ids = (await db.execute(select(RackPort.id).where(RackPort.rack_item_id == item_id))).scalars().all()
    if port_ids:
        await db.execute(delete(RackCable).where(or_(RackCable.a_port_id.in_(port_ids), RackCable.b_port_id.in_(port_ids))))
        await db.execute(delete(RackPort).where(RackPort.id.in_(port_ids)))
    await db.delete(item)
    await db.commit()
    return {"message": "Rack item deleted"}


@router.put("/ports", response_model=list[PortOut])
async def set_ports(data: PortsIn, db: AsyncSession = Depends(get_db)):
    """Set how many ports a device or rack item has, and what kind they are."""
    if data.owner_type == "device":
        owner, owner_field = await db.get(DeviceModel, data.owner_id), "device_id"
    else:
        owner, owner_field = await db.get(RackItem, data.owner_id), "rack_item_id"
    if owner is None:
        raise HTTPException(status_code=404, detail="Owner not found")
    await _set_ports(db, owner_field, data.owner_id, data.count, data.kind, data.side)
    await db.commit()
    column = getattr(RackPort, owner_field)
    return (await db.execute(select(RackPort).where(column == data.owner_id).order_by(RackPort.number))).scalars().all()


@router.post("/rack-cables", response_model=CableOut)
async def create_cable(data: CableIn, db: AsyncSession = Depends(get_db)):
    if data.a_port_id == data.b_port_id:
        raise HTTPException(status_code=422, detail="A cable needs two different ports")
    ports = {
        port.id: port
        for port in (await db.execute(select(RackPort).where(RackPort.id.in_([data.a_port_id, data.b_port_id])))).scalars().all()
    }
    if len(ports) != 2:
        raise HTTPException(status_code=404, detail="Port not found")
    a, b = ports[data.a_port_id], ports[data.b_port_id]
    if (a.device_id, a.rack_item_id) == (b.device_id, b.rack_item_id):
        raise HTTPException(status_code=422, detail="Both ends are on the same device")
    if await _cabled_port_ids(db, [a.id, b.id]):
        raise HTTPException(status_code=409, detail="A port already has a cable")
    cable = RackCable(a_port_id=a.id, b_port_id=b.id, cable=data.cable, color=data.color, notes=data.notes)
    db.add(cable)
    await db.commit()
    await db.refresh(cable)
    return cable


@router.patch("/rack-cables/{cable_id}", response_model=CableOut)
async def update_cable(cable_id: int, patch: CablePatch, db: AsyncSession = Depends(get_db)):
    cable = await db.get(RackCable, cable_id)
    if cable is None:
        raise HTTPException(status_code=404, detail="Cable not found")
    values = patch.model_dump(exclude_unset=True)
    if "cable" in values and values["cable"] is None:
        raise HTTPException(status_code=422, detail="A cable needs a type")
    for field, value in values.items():
        setattr(cable, field, value)
    await db.commit()
    await db.refresh(cable)
    return cable


@router.delete("/rack-cables/{cable_id}")
async def delete_cable(cable_id: int, db: AsyncSession = Depends(get_db)):
    cable = await db.get(RackCable, cable_id)
    if cable is None:
        raise HTTPException(status_code=404, detail="Cable not found")
    await db.delete(cable)
    await db.commit()
    return {"message": "Cable deleted"}
