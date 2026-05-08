import asyncio
import httpx

async def test_setup_status():
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://localhost:8000/api/setup/status")
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.json()}")
        except Exception as e:
            print(f"Failed to reach backend: {e}")

if __name__ == "__main__":
    asyncio.run(test_setup_status())
