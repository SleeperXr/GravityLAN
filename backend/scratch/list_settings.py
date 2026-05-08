import asyncio
from sqlalchemy import select
from app.database import async_session
from app.models.setting import Setting

async def list_settings():
    async with async_session() as db:
        result = await db.execute(select(Setting))
        settings = result.scalars().all()
        for s in settings:
            print(f"{s.key}: {s.value} ({s.category})")

if __name__ == "__main__":
    asyncio.run(list_settings())
