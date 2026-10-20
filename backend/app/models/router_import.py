"""SQLAlchemy model for the saved router connections of the subnet import.

Secrets (SNMP community, SNMPv3 keys, UniFi API key) are only ever stored
encrypted (see app.services.secret_vault); encrypted_secrets never leaves the backend.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RouterImportSource(Base):
    """The last router a provider imported from: one row per provider.

    options holds the non-secret settings as JSON (SNMP version and user, UniFi site,
    pinned TLS fingerprint); encrypted_secrets holds the secrets as one encrypted JSON object.
    """

    __tablename__ = "router_import_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    options: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    encrypted_secrets: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
