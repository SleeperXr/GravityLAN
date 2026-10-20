"""ORM models package — import all models to ensure table registration."""

from app.models.device import Device, DeviceGroup, DeviceInterface, Service, DiscoveredHost, DeviceHistory, DeviceHealthSample
from app.models.setting import Setting
from app.models.agent import AgentToken, DeviceMetrics, AgentConfig
from app.models.telemetry import DeviceHealthRollup, DeviceMetricsRollup
from app.models.network import Subnet
from app.models.topology import Rack, TopologyLink
from app.models.api_token import ApiToken
from app.models.webhook import WebhookSubscription
from app.models.router_import import RouterImportSource

__all__ = [
    "Device", "DeviceGroup", "DeviceInterface", "Service", "DiscoveredHost", "DeviceHistory", "DeviceHealthSample",
    "Setting", "AgentToken", "DeviceMetrics", "AgentConfig", "Subnet",
    "DeviceHealthRollup", "DeviceMetricsRollup",
    "Rack", "TopologyLink", "ApiToken", "WebhookSubscription", "RouterImportSource"
]
