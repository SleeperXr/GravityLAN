"""Migration script — Create agent tables (agent_tokens, device_metrics, agent_configs).

Run once: python migrate_agent_tables.py
"""

import asyncio
import sys
from pathlib import Path

# Add backend root to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from app.database import engine, Base
from app.models.agent import AgentToken, DeviceMetrics, AgentConfig  # noqa: F401


async def migrate() -> None:
    """Create agent-related tables in the database."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Agent tables created successfully:")
    print("   - agent_tokens")
    print("   - device_metrics")
    print("   - agent_configs")


if __name__ == "__main__":
    asyncio.run(migrate())
