
import asyncio
from app.database import async_session
from app.models.setting import SystemSetting
from sqlalchemy import select

async def fix():
    async with async_session() as db:
        settings = {
            'is_setup_complete': 'true',
            'scan_interval': '10',
            'quick_scan_interval': '300',
            'history_retention_days': '7'
        }
        for key, value in settings.items():
            result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
            if not result.scalar_one_or_none():
                db.add(SystemSetting(key=key, value=value))
                print(f"Added missing setting: {key}={value}")
        await db.commit()
        print("Database settings verification complete.")

if __name__ == "__main__":
    asyncio.run(fix())
