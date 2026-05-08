"""SQLAlchemy model for all application and system settings."""

from sqlalchemy import String, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Setting(Base):
    """Unified settings store for application configuration and system state.
    
    Attributes:
        key: Unique setting key (e.g. 'setup.complete', 'scan_interval').
        value: Setting value as string.
        category: Grouping category (system, ui, scan, etc.).
        description: Optional human-readable description.
    """
    __tablename__ = "app_settings" # Re-use the existing table name that has data

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
