"""scripts/dev_demo.py seeds every scenario into an empty database, and a second start only re-issues agent tokens."""

import hashlib
import random
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import Base

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import dev_demo  # noqa: E402
from demo_scenarios import SCENARIOS  # noqa: E402

from app.models.agent import AgentToken, DeviceMetrics  # noqa: E402
from app.models.device import Device, DeviceHealthSample, Service  # noqa: E402
from app.models.rack_cabling import RackCable  # noqa: E402
from app.models.topology import TopologyLink  # noqa: E402


@pytest.fixture
def seed_into_test_db(db, monkeypatch):
    async def nothing(*_a, **_k):
        return None

    # The test database's own engine (importing conftest again would build a second, empty one)
    monkeypatch.setattr("app.database.async_session", async_sessionmaker(bind=db.bind, expire_on_commit=False, class_=AsyncSession))
    monkeypatch.setattr("app.database.init_db", nothing)
    monkeypatch.setattr("app.database.migrations.run_migrations", nothing)
    return db


async def snapshot(db) -> str:
    """Every row of every table, without secrets and times, as one digest."""
    skip = {"token", "value", "timestamp", "last_seen", "first_seen", "status_changed_at", "ip_changed_at", "created_at", "updated_at"}
    digest = hashlib.sha256()
    for table in Base.metadata.sorted_tables:
        cols = [c.name for c in table.columns if c.name not in skip]
        name = f"{table.schema}.{table.name}" if table.schema else table.name
        rows = (await db.execute(text(f"SELECT {', '.join(cols)} FROM {name} ORDER BY 1"))).all()
        digest.update(f"{name}:{rows!r}".encode())
    return digest.hexdigest()


@pytest.mark.parametrize("key", sorted(SCENARIOS))
@pytest.mark.asyncio
async def test_seed_fills_the_scenario(seed_into_test_db, key):
    db = seed_into_test_db
    scenario = SCENARIOS[key]()
    random.seed(7)
    agents = await dev_demo._seed(scenario)

    count = lambda model: db.execute(select(func.count()).select_from(model))  # noqa: E731
    assert (await count(Device)).scalar_one() == len(scenario.devices)
    assert (await count(Service)).scalar_one() == sum(len(d[5]) for d in scenario.devices)
    assert (await count(TopologyLink)).scalar_one() == len(scenario.links)
    assert (await count(RackCable)).scalar_one() == len(scenario.cables)
    with_agent = [d[0] for d in scenario.devices if d[6]]
    assert sorted(agents) == sorted(with_agent)
    assert (await count(AgentToken)).scalar_one() == len(with_agent)
    assert (await count(DeviceMetrics)).scalar_one() == 288 * len(with_agent)
    assert (await count(DeviceHealthSample)).scalar_one() == 288 * len(scenario.devices)

    # Parents, rack places and grid positions come from the scenario
    by_name = {d.display_name: d for d in (await db.execute(select(Device))).scalars()}
    for name, _ip, _t, _g, flags, _s, _p in scenario.devices:
        if flags.get("parent"):
            assert by_name[name].parent_id == by_name[flags["parent"]].id
    for name, (_rack, unit, height) in scenario.rack_slots.items():
        assert (by_name[name].rack_unit, by_name[name].rack_height) == (unit, height)

    # A second start keeps the data and hands the simulated agents new tokens
    before = await snapshot(db)
    again = await dev_demo._seed(scenario)
    assert {n: (i, p) for n, (i, _t, p) in again.items()} == {n: (i, p) for n, (i, _t, p) in agents.items()}
    assert all(again[n][1] != agents[n][1] for n in agents)
    assert await snapshot(db) == before
