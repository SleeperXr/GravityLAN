from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

class Rack(Base):
    """Represents a physical server rack."""
    __tablename__ = "racks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    units: Mapped[int] = mapped_column(Integer, default=42) # Total Height in U
    width: Mapped[int] = mapped_column(Integer, default=19) # Standard 19"
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    devices: Mapped[list["Device"]] = relationship("Device", back_populates="rack")

class TopologyLink(Base):
    """Represents a network connection between two devices."""
    __tablename__ = "topology_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.id"), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.id"), nullable=False)
    
    # Connection metadata
    link_type: Mapped[str] = mapped_column(String(50), default="1GbE") # 10GbE, 2.5GbE, 1GbE, WLAN, Fiber
    speed: Mapped[int | None] = mapped_column(Integer, nullable=True) # Mbps
    color: Mapped[str | None] = mapped_column(String(7), nullable=True) # Cable color hex
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
