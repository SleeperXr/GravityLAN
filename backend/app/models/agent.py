"""SQLAlchemy ORM models for agent tokens and device metrics."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgentToken(Base):
    """Authentication token for a deployed HomeLan Agent.

    Each device gets exactly one token generated during SSH deployment.
    The token authenticates the agent's metric reports.

    Attributes:
        id: Primary key.
        device_id: Foreign key to the monitored device.
        token: Unique bearer token string (UUID4).
        is_active: Whether the token is currently valid.
        agent_version: Last reported agent version string.
        created_at: Token creation timestamp.
        last_seen: Last successful report timestamp.
    """

    __tablename__ = "agent_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    agent_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    device: Mapped["Device"] = relationship()  # noqa: F821


class DeviceMetrics(Base):
    """Time-series storage for agent-reported system metrics.

    Each row represents one snapshot of a device's health at a point in time.
    Old entries can be pruned periodically to save storage.

    Attributes:
        id: Primary key.
        device_id: Foreign key to the monitored device.
        cpu_percent: CPU utilization (0.0 – 100.0).
        ram_used_mb: Used RAM in megabytes.
        ram_total_mb: Total RAM in megabytes.
        ram_percent: RAM usage percentage.
        disk_json: JSON string with per-mount disk usage.
        temperature: CPU temperature in Celsius (None if unavailable).
        net_json: JSON string with per-interface network I/O.
        timestamp: When the metrics were collected.
    """

    __tablename__ = "device_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cpu_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ram_used_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ram_total_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ram_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    disk_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    device: Mapped["Device"] = relationship()  # noqa: F821

    def to_dict(self):
        """Convert metrics to a dictionary for API responses (WebSocket snapshot format)."""
        import json
        return {
            "device_id": self.device_id,
            "cpu_percent": self.cpu_percent,
            "ram": {
                "used_mb": self.ram_used_mb,
                "total_mb": self.ram_total_mb,
                "percent": self.ram_percent
            },
            "disk": json.loads(self.disk_json) if self.disk_json else [],
            "temperature": self.temperature,
            "network": json.loads(self.net_json) if self.net_json else {},
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }


class AgentConfig(Base):
    """Per-device agent configuration stored server-side.

    Pushed to the agent in the HTTP response body after each report.
    Allows the user to configure disk paths and temperature monitoring
    from the HomeLan UI without SSH access.

    Attributes:
        id: Primary key.
        device_id: Foreign key to the monitored device.
        interval: Reporting interval in seconds.
        disk_paths_json: JSON list of mount paths to monitor.
        enable_temp: Whether to collect temperature metrics.
    """

    __tablename__ = "agent_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    interval: Mapped[int] = mapped_column(Integer, default=30)
    version: Mapped[int] = mapped_column(Integer, default=1)
    disk_paths_json: Mapped[str] = mapped_column(Text, default='["/"]')
    enable_temp: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def disk_paths(self) -> list[str]:
        """Deserialize disk_paths_json to a list."""
        import json
        if not self.disk_paths_json:
            return ["/"]
        try:
            return json.loads(self.disk_paths_json)
        except (ValueError, TypeError):
            return ["/"]

    @disk_paths.setter
    def disk_paths(self, paths: list[str]):
        """Serialize a list to disk_paths_json."""
        import json
        self.disk_paths_json = json.dumps(paths)
