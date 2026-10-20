"""Async SQLAlchemy database engine and session management.

Two SQLite files share one engine: the inventory (``gravitylan.db``) is the main
schema, and the measurement data (health samples, agent metrics and their rollups)
lives in ``telemetry.db``, attached to every connection as schema ``telemetry``.
Queries and sessions stay the same for both; the telemetry file can be sized,
vacuumed and wiped on its own and is not part of a backup.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


from sqlalchemy import event

# Schema name of the telemetry models (``__table_args__ = {"schema": TELEMETRY_SCHEMA}``)
TELEMETRY_SCHEMA = "telemetry"

_IS_SQLITE = "sqlite" in settings.effective_database_url

engine = create_async_engine(
    settings.effective_database_url,
    echo=False,
    connect_args={
        "check_same_thread": False,
        "timeout": 30
    } if _IS_SQLITE else {},
    # SQLite works best with a small connection pool.
    # WAL mode handles concurrent reads, but writes are still serialized.
    pool_size=5 if _IS_SQLITE else 20,
    max_overflow=10 if _IS_SQLITE else 20,
    # Other databases keep the telemetry tables in their default schema
    execution_options={} if _IS_SQLITE else {"schema_translate_map": {TELEMETRY_SCHEMA: None}},
)


def attach_telemetry_database(dbapi_connection, path: str) -> None:
    """Attach the telemetry file as schema ``telemetry`` and configure it.

    auto_vacuum only takes effect on a file without tables, i.e. on its first
    attach, which is when init_db creates them; afterwards it is a no-op.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute(f"ATTACH DATABASE ? AS {TELEMETRY_SCHEMA}", (path,))
    cursor.execute(f"PRAGMA {TELEMETRY_SCHEMA}.auto_vacuum=INCREMENTAL")
    cursor.execute(f"PRAGMA {TELEMETRY_SCHEMA}.journal_mode=WAL")
    cursor.execute(f"PRAGMA {TELEMETRY_SCHEMA}.synchronous=NORMAL")
    cursor.close()


# Enable WAL mode for SQLite to prevent "database is locked" errors
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
        attach_telemetry_database(dbapi_connection, settings.telemetry_database_path)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session.

    Ensures the session is properly closed after the request completes.
    """
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Create all database tables (inventory and telemetry) if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
