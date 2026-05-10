import asyncio
from app.database import async_session
from app.models.setting import Setting
from sqlalchemy import select

async def dump_settings():
    async with async_session() as db:
        res = await db.execute(select(Setting))
        settings = res.scalars().all()
        print(f"--- Settings Dump ({len(settings)} items) ---")
        for s in settings:
            # Mask sensitive values
            val = s.value
            if "token" in s.key or "password" in s.key:
                val = f"{val[:4]}...{val[-4:]}" if val and len(val) > 8 else "***"
            print(f"{s.key}: {val}")

if __name__ == "__main__":
    asyncio.run(dump_settings())
