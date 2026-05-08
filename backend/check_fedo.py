
import asyncio
from app.database import async_session
from app.models.device import Device
from sqlalchemy import select

async def check():
    async with async_session() as db:
        result = await db.execute(select(Device).where(Device.ip == '192.168.100.3'))
        dev = result.scalar_one_or_none()
        if dev:
            print(f"FEDO_STATUS: {'ONLINE' if dev.is_online else 'OFFLINE'}")
            print(f"LAST_SEEN: {dev.last_seen}")
        else:
            print("FEDO_STATUS: not_found")

if __name__ == "__main__":
    asyncio.run(check())
