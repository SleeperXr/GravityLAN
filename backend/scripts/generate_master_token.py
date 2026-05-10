import asyncio
import secrets
from app.database import async_session
from app.models.setting import Setting
from sqlalchemy import select

async def generate_token():
    async with async_session() as db:
        res = await db.execute(select(Setting).where(Setting.key == "api.master_token"))
        existing = res.scalar_one_or_none()
        
        if existing:
            print(f"Existing Master Token: {existing.value}")
        else:
            token = secrets.token_hex(32)
            db.add(Setting(key="api.master_token", value=token))
            print(f"Generated NEW Master Token: {token}")

        # Ensure admin password exists
        res_pass = await db.execute(select(Setting).where(Setting.key == "api.admin_password"))
        if not res_pass.scalar_one_or_none():
            db.add(Setting(key="api.admin_password", value="gravitylan"))
            print("Default Admin Password set to: gravitylan")
            print("You can change this in the Dashboard settings.")
        
        await db.commit()

if __name__ == "__main__":
    asyncio.run(generate_token())
