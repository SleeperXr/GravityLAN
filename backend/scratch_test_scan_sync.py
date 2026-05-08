import asyncio
import os
import sys

# Add backend to path so we can import app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.models.device import Device, Service, Base, DiscoveredHost, DeviceGroup
from app.scanner.classifier import classify_device

# Mock the database for testing
TEST_DB_URL = "sqlite+aiosqlite:///test_scan_sync.db"
engine = create_async_engine(TEST_DB_URL)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def test_logic():
    print("--- Starting Port Sync Test ---")
    
    # Initialize test DB
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Monkeypatch the scanner's session
    import app.api.scanner
    app.api.scanner.async_session = async_session
    from app.api.scanner import _persist_to_discovery_table

    async with async_session() as db:
        # 1. Create a device with NO services
        print("Step 1: Creating device with no services...")
        dev = Device(
            ip="192.168.1.10",
            display_name="Test Device",
            device_type="unknown",
            device_subtype="Unknown",
            is_online=False
        )
        db.add(dev)
        
        # Add a manual service that should stay
        manual_svc = Service(
            device=dev,
            name="Manual Service",
            protocol="tcp",
            port=1234,
            is_auto_detected=False,
            is_up=True
        )
        db.add(manual_svc)
        
        await db.commit()
        
        # 2. Simulate a scan result with SSH and HTTP ports
        print("Step 2: Simulating scan result with ports [22, 80]...")
        alive_hosts = [
            {
                "ip": "192.168.1.10",
                "hostname": "SERVER-01",
                "ports": [22, 80],
                "mac": "AA:BB:CC:DD:EE:FF"
            }
        ]
        
        # 3. Call the logic
        print("Step 3: Running persist logic...")
        await _persist_to_discovery_table(alive_hosts, ["192.168.1.0/24"])
        
        # 4. Verify results
        print("\nStep 4: Verifying results...")
        # Need to expire and re-fetch or use a new session
        
    async with async_session() as db:
        result = await db.execute(select(Device).where(Device.ip == "192.168.1.10"))
        updated_dev = result.scalar_one()
        
        print(f"Device IP: {updated_dev.ip}")
        print(f"Device type: {updated_dev.device_type} (Expected: server/webui)")
        print(f"Device subtype: {updated_dev.device_subtype}")
        print(f"Online: {updated_dev.is_online} (Expected: True)")
        
        services = updated_dev.services
        print(f"Services found: {len(services)}")
        
        has_ssh = any(s.port == 22 and s.is_auto_detected for s in services)
        has_http = any(s.port == 80 and s.is_auto_detected for s in services)
        has_manual = any(s.port == 1234 and not s.is_auto_detected for s in services)
        
        print(f" - SSH (22) auto-added: {has_ssh}")
        print(f" - HTTP (80) auto-added: {has_http}")
        print(f" - Manual (1234) preserved: {has_manual}")
        
        if has_ssh and has_http and has_manual and updated_dev.is_online:
            print("\n✅ TEST PASSED")
        else:
            print("\n❌ TEST FAILED")

    # Cleanup
    if os.path.exists("test_scan_sync.db"):
        os.remove("test_scan_sync.db")

if __name__ == "__main__":
    asyncio.run(test_logic())
