"""Async SQLAlchemy database engine and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


from sqlalchemy import event

engine = create_async_engine(
    settings.effective_database_url,
    echo=False,
    connect_args={
        "check_same_thread": False,
        "timeout": 30
    } if "sqlite" in settings.effective_database_url else {},
    # SQLite works best with a small connection pool. 
    # WAL mode handles concurrent reads, but writes are still serialized.
    pool_size=5 if "sqlite" in settings.effective_database_url else 20,
    max_overflow=10 if "sqlite" in settings.effective_database_url else 20,
)

# Enable WAL mode for SQLite to prevent "database is locked" errors
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in settings.effective_database_url:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

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
    """Create all database tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
