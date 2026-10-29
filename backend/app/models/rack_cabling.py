"""Rack equipment that is not part of the network inventory, its ports, and the cables between ports.

Network devices keep their rack placement on the device row. Everything else (unmanaged switches, UPS units,
patch panels, phone systems, blanking panels, cable management) is a RackItem. Both kinds own ports, and a
RackCable joins two ports physically. This is the cabling of the rack, separate from the logical TopologyLink
that the orbit map draws.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RackItem(Base):
    """A rack-mounted piece of equipment without its own place in the network inventory."""

    __tablename__ = "rack_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rack_id: Mapped[int] = mapped_column(Integer, ForeignKey("racks.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    rack_unit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rack_height: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RackPort(Base):
    """One port of a device or a rack item. Exactly one of device_id and rack_item_id is set."""

    __tablename__ = "rack_ports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=True, index=True)
    rack_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("rack_items.id", ondelete="CASCADE"), nullable=True, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="RJ45")
    # Which side of the rack the port is on: front (switches, patch panels) or rear (servers, power)
    side: Mapped[str] = mapped_column(String(10), nullable=False, default="front", server_default="front")

    __table_args__ = (
        UniqueConstraint("device_id", "number", name="uix_rack_port_device"),
        UniqueConstraint("rack_item_id", "number", name="uix_rack_port_item"),
        CheckConstraint("(device_id IS NULL) != (rack_item_id IS NULL)", name="ck_rack_port_one_owner"),
    )


class RackCable(Base):
    """A physical cable between two ports. A port carries at most one cable (checked by the API)."""

    __tablename__ = "rack_cables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    a_port_id: Mapped[int] = mapped_column(Integer, ForeignKey("rack_ports.id", ondelete="CASCADE"), nullable=False, index=True)
    b_port_id: Mapped[int] = mapped_column(Integer, ForeignKey("rack_ports.id", ondelete="CASCADE"), nullable=False, index=True)
    cable: Mapped[str] = mapped_column(String(40), nullable=False, default="Cat6")
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (CheckConstraint("a_port_id != b_port_id", name="ck_rack_cable_two_ports"),)
