"""Pydantic schemas for Webhook Subscriptions."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, field_validator

class WebhookSubscriptionCreate(BaseModel):
    url: str = Field(..., description="Target URL for webhook POST requests")
    events: list[str] = Field(..., description="List of events to subscribe to (e.g. ['device.offline', 'scan.complete'])")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Must be a valid HTTP or HTTPS URL")
        return v

class WebhookSubscriptionResponse(BaseModel):
    id: int
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime

    @field_validator("events", mode="before")
    @classmethod
    def parse_events(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [e.strip() for e in v.split(",") if e.strip()]
        return v

    class Config:
        from_attributes = True
