import asyncio
import logging
from app.services.agent_deployer import deploy_agent

logging.basicConfig(level=logging.INFO)

async def test():
    # Attempting to deploy to the IP from the screenshot
    # Note: I don't have the password, so this is just to check local setup/errors
    success, msg, token = await deploy_agent(
        host_ip="192.168.100.2",
        ssh_user="root",
        ssh_password="DUMMY_PASSWORD", 
        server_url="http://192.168.100.50:8000",
        device_id=2
    )
    print(f"Success: {success}")
    print(f"Message: {msg}")

if __name__ == "__main__":
    asyncio.run(test())
