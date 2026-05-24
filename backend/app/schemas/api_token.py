"""Pydantic schemas for Personal Access Token (API Key) management."""

from datetime import datetime
from pydantic import BaseModel, Field

class ApiTokenCreate(BaseModel):
    name: str = Field(..., description="Descriptive name for the API Token (e.g. Home Assistant)")

class ApiTokenResponse(BaseModel):
    id: int
    name: str
    prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None

    class Config:
        from_attributes = True

class ApiTokenCreated(ApiTokenResponse):
    token: str = Field(..., description="Plaintext token value, returned ONLY ONCE during creation.")
