"""Application configuration via environment variables and Pydantic Settings."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
import socket
from app.version import VERSION


def _default_data_dir() -> Path:
    """Return default data directory: /app/data inside containers, otherwise ./data."""
    if Path("/app").is_dir():
        return Path("/app/data")
    return Path("./data")


def process_ids() -> tuple[int, int]:
    """Return the UID and GID this process runs as, for permission hints.

    Platforms without POSIX IDs (Windows) get the image default 1000:1000.
    """
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    gid = os.getgid() if hasattr(os, "getgid") else 1000
    return uid, gid


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Attributes:
        app_name: Display name of the application.
        app_version: Current version string.
        debug: Enable debug mode with verbose logging.
        data_dir: Persistent data directory for SQLite DB and config.
        database_url: SQLAlchemy-compatible database URL.
        scan_timeout: Socket connect timeout in seconds per port.
        scan_workers: Maximum concurrent scan workers.
        scan_interval_minutes: Auto-scan interval (0 = disabled).
        cors_origins: Allowed CORS origins for development.
    """

    app_name: str = "GravityLAN"
    app_version: str = VERSION
    # Image build label from the Dockerfile ("dev+<commit>"); empty for releases and local runs
    build: str = ""
    debug: bool = False
    secure_cookies: bool = False
    ssh_strict_mode: bool = False
    # LAN IP of the machine running the container. Only SSH logins to exactly this address may
    # retry on the Docker bridge gateway (#46); empty = never (DOCKER_HOST_IP is read as well).
    docker_host_ip: str = ""
    # Let the manual installer run over plain HTTP without ALLOW_INSECURE=1 on the device (#44)
    allow_insecure_install: bool = False
    history_retention_days: int = 30

    # SSH terminal / secret vault
    vault_key: str = Field(default="", description="Fernet key for stored secrets; empty = <data_dir>/ssh_vault.key")
    ssh_idle_timeout_minutes: int = Field(default=30, description="Close terminal sessions without input after N minutes (0 = never)")
    ssh_max_sessions: int = Field(default=10, description="Maximum concurrent browser SSH sessions")

    # Paths
    data_dir: Path = Field(
        default_factory=_default_data_dir,
        description="Persistent data directory for SQLite DB and config.",
    )
    database_url: str = ""

    # Scanner
    scan_timeout: float = Field(default=1.5, description="Socket connect timeout in seconds per port")
    scan_workers: int = Field(default=20, description="Maximum concurrent scan workers")
    scan_interval_minutes: int = Field(default=0, description="Auto-scan interval (0 = disabled)")

    # Server
    host: str = Field(default="0.0.0.0", description="Host address to bind to")
    port: int = Field(default=8000, description="Port to listen on")

    # CORS (development)
    cors_origins: list[str] = []

    model_config = {"env_prefix": "GRAVITYLAN_", "env_file": ".env"}

    @field_validator("scan_timeout")
    @classmethod
    def validate_scan_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("scan_timeout must be greater than 0")
        return v

    @field_validator("scan_workers")
    @classmethod
    def validate_scan_workers(cls, v: int) -> int:
        if not (1 <= v <= 200):
            raise ValueError("scan_workers must be between 1 and 200")
        return v

    @field_validator("scan_interval_minutes")
    @classmethod
    def validate_scan_interval(cls, v: int) -> int:
        if v < 0:
            raise ValueError("scan_interval_minutes must be greater than or equal to 0")
        return v

    @field_validator("history_retention_days")
    @classmethod
    def validate_history_retention(cls, v: int) -> int:
        if not (1 <= v <= 365):
            raise ValueError("history_retention_days must be between 1 and 365")
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("port must be between 1 and 65535")
        return v

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        v_clean = v.strip()
        if not v_clean:
            raise ValueError("host cannot be empty")
            
        if v_clean in ("0.0.0.0", "::", "localhost"):
            return v_clean
            
        # Validate as IPv4
        try:
            socket.inet_pton(socket.AF_INET, v_clean)
            return v_clean
        except socket.error:
            pass
            
        # Validate as IPv6
        try:
            socket.inet_pton(socket.AF_INET6, v_clean)
            return v_clean
        except socket.error:
            pass
            
        # Validate as a hostname (RFC 1123)
        if len(v_clean) > 253:
            raise ValueError("host name is too long")
        
        labels = v_clean.split(".")
        for label in labels:
            if not label:
                raise ValueError("host labels cannot be empty")
            if len(label) > 63:
                raise ValueError("host label is too long")
            if not (label[0].isalnum() and label[-1].isalnum()):
                raise ValueError("host labels must start and end with an alphanumeric character")
            if not all(c.isalnum() or c == "-" for c in label):
                raise ValueError("host name contains invalid characters")
                
        return v_clean


    @property
    def effective_database_url(self) -> str:
        """Return the database URL, defaulting to SQLite in data_dir."""
        if self.database_url:
            return self.database_url
        db_path = self.data_dir / "gravitylan.db"
        return f"sqlite+aiosqlite:///{db_path}"

    @property
    def telemetry_database_path(self) -> str:
        """SQLite file for measurement data (health probes, agent metrics, rollups).

        Lives next to the inventory database and is attached to every connection as
        schema ``telemetry``; an in-memory inventory gets an in-memory telemetry DB.
        Empty for non-SQLite databases, where the telemetry tables share the main schema.
        """
        url = self.effective_database_url
        if "sqlite" not in url:
            return ""
        main_path = url.split(":///", 1)[1] if ":///" in url else ""
        if not main_path or main_path == ":memory:":
            return ":memory:"
        return str(Path(main_path).with_name("telemetry.db"))


settings = Settings()
