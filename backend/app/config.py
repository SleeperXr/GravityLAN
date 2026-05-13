"""Application configuration via environment variables and Pydantic Settings."""

from pathlib import Path

from pydantic_settings import BaseSettings


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
    app_version: str = "0.1.0"
    debug: bool = False
    secure_cookies: bool = False

    # Paths
    data_dir: Path = Path("/app/data")
    database_url: str = ""

    # Scanner
    scan_timeout: float = 1.5
    scan_workers: int = 20
    scan_interval_minutes: int = 0

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS (development)
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    model_config = {"env_prefix": "GRAVITYLAN_", "env_file": ".env"}

    @property
    def effective_database_url(self) -> str:
        """Return the database URL, defaulting to SQLite in data_dir."""
        if self.database_url:
            return self.database_url
        db_path = self.data_dir / "gravitylan.db"
        return f"sqlite+aiosqlite:///{db_path}"


settings = Settings()
