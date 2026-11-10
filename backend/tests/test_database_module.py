"""The database module's own helpers (app/database/__init__.py), which the test client overrides elsewhere."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as database


@pytest.mark.asyncio
async def test_get_db_yields_a_session_and_closes_it(monkeypatch):
    closed = []
    original_close = AsyncSession.close

    async def close(self):
        closed.append(self)
        await original_close(self)

    monkeypatch.setattr(AsyncSession, "close", close)
    gen = database.get_db()
    session = await gen.__anext__()
    assert isinstance(session, AsyncSession)
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert session in closed


@pytest.mark.asyncio
async def test_init_db_creates_every_table(monkeypatch):
    ran = []

    class Conn:
        async def run_sync(self, fn):
            ran.append(fn)

    class Begin:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(database, "engine", type("Engine", (), {"begin": lambda self: Begin()})())
    await database.init_db()
    assert ran == [database.Base.metadata.create_all]
