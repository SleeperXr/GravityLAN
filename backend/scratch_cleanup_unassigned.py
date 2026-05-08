import asyncio
from sqlalchemy import select, delete
from app.database import async_session
from app.models.device import Device

async def cleanup():
    async with async_session() as session:
        # Delete all devices that are NOT assigned to a group
        # This cleans up the auto-added devices from the recent scan
        stmt = delete(Device).where(Device.group_id == None)
        result = await session.execute(stmt)
        await session.commit()
        print(f"Deleted {result.rowcount} unassigned devices.")

if __name__ == "__main__":
    asyncio.run(cleanup())
