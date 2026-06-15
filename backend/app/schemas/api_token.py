from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, field_validator

class ApiTokenCreate(BaseModel):
    name: str = Field(..., description="Descriptive name for the API Token (e.g. Home Assistant)")
    scopes: list[str] | None = Field(default=None, description="Optional list of scopes for the token")

class ApiTokenResponse(BaseModel):
    id: int
    name: str
    prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    scopes: list[str] | None = None

    @field_validator("scopes", mode="before")
    @classmethod
    def parse_scopes(cls, v: Any) -> list[str] | None:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    class Config:
        from_attributes = True

class ApiTokenCreated(ApiTokenResponse):
    token: str = Field(..., description="Plaintext token value, returned ONLY ONCE during creation.")

