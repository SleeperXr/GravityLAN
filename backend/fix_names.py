import asyncio
import sys
import os

# Add backend to path
sys.path.append(os.getcwd())

from app.database import async_session
from app.models.device import Device
from sqlalchemy import select
from app.scanner.hostname import resolve_hostname

async def fix_names():
    print("--- Starting Name Cleanup ---")
    async with async_session() as db:
        res = await db.execute(select(Device))
        devices = res.scalars().all()
        
        for d in devices:
            # Only try to fix if it's an IP or empty
            is_ip = d.display_name.replace(".", "").isdigit()
            if is_ip or not d.display_name:
                name = await resolve_hostname(d.ip, timeout=3.0)
                if name:
                    d.hostname = name
                    d.display_name = name.split('.')[0]
                    print(f"Fixed: {d.ip} -> {d.display_name}")
                else:
                    print(f"Skipped: {d.ip} (No hostname found)")
        
        await db.commit()
    print("--- Cleanup Finished ---")

if __name__ == "__main__":
    asyncio.run(fix_names())
