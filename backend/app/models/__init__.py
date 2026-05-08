"""ORM models package — import all models to ensure table registration."""

from app.models.device import Device, DeviceGroup, Service
from app.models.setting import Setting
from app.models.agent import AgentToken, DeviceMetrics, AgentConfig

__all__ = [
    "Device", "DeviceGroup", "Service", "Setting",
    "AgentToken", "DeviceMetrics", "AgentConfig",
]
