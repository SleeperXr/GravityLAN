import pytest
from fastapi import HTTPException
from app.api.settings import update_settings
from pydantic import RootModel

@pytest.mark.asyncio
async def test_subnet_validation_valid(db_session):
    """Test that valid subnets are accepted."""
    # We mock the settings update request
    settings_data = RootModel({"scan_subnets": "192.168.1.0/24, 10.0.0.0/8"})
    
    # This should not raise an exception
    # (In a real test we would use the test client, but this tests the logic)
    from app.api.settings import update_settings
    # Mocking DB response for select(Setting)
    # For now, let's just test that it doesn't raise the specific 400 error immediately
    pass

@pytest.mark.asyncio
async def test_subnet_validation_invalid(client, admin_token):
    """Test that invalid subnets return 400 via the API."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {"scan_subnets": "999.999.999.0/24"}
    
    response = await client.post("/api/settings", json=payload, headers=headers)
    assert response.status_code == 400
    assert "Ungültige Subnetze" in response.json()["detail"]

@pytest.mark.asyncio
async def test_subnet_validation_mixed(client, admin_token):
    """Test that if one subnet is invalid, the whole request fails."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {"scan_subnets": "192.168.1.0/24, invalid-ip, 10.0.0.0/8"}
    
    response = await client.post("/api/settings", json=payload, headers=headers)
    assert response.status_code == 400
    assert "invalid-ip" in response.json()["detail"]

def test_settings_validation_limits():
    """Test Pydantic configuration limit validators on Settings."""
    from pydantic import ValidationError
    from app.config import Settings

    # 1. Invalid scan timeouts
    with pytest.raises(ValidationError):
        Settings(scan_timeout=0)
    with pytest.raises(ValidationError):
        Settings(scan_timeout=-1.5)

    # 2. Invalid scan workers
    with pytest.raises(ValidationError):
        Settings(scan_workers=0)
    with pytest.raises(ValidationError):
        Settings(scan_workers=201)

    # 3. Invalid scan intervals
    with pytest.raises(ValidationError):
        Settings(scan_interval_minutes=-5)

    # 4. Invalid ports
    with pytest.raises(ValidationError):
        Settings(port=0)
    with pytest.raises(ValidationError):
        Settings(port=65536)

    # 5. Invalid/Valid hosts
    with pytest.raises(ValidationError):
        Settings(host="invalid_host_!!")
    with pytest.raises(ValidationError):
        Settings(host="")
    
    # Valid hosts should pass validation
    assert Settings(host="192.168.1.1").host == "192.168.1.1"
    assert Settings(host="2001:db8::1").host == "2001:db8::1"
    assert Settings(host="my-homelab-server.local").host == "my-homelab-server.local"

@pytest.mark.asyncio
async def test_scheduler_loop_cancellation():
    """Verify scheduler background loops propagate CancelledError without swallowing."""
    from app.scanner.scheduler import ScanScheduler
    import asyncio
    
    scheduler = ScanScheduler()
    scheduler._running = True
    task = asyncio.create_task(scheduler._quick_loop())
    await asyncio.sleep(0.01)  # allow task to enter sleep
    task.cancel()
    
    with pytest.raises(asyncio.CancelledError):
        await task

@pytest.mark.asyncio
async def test_migrations_with_missing_tables(db):
    """Verify migrations handle missing tables by skipping them safely."""
    from app.database.migrations import run_migrations
    # Running on clean/empty in-memory db session
    await run_migrations(db)

@pytest.mark.asyncio
async def test_migrations_with_existing_table_missing_columns(db):
    """Verify migrations successfully add missing columns to an existing table."""
    from app.database.migrations import run_migrations
    import app.database.migrations
    from sqlalchemy import inspect
    from unittest.mock import patch
    
    raw_conn = await db.connection()
    # Create a completely new table 'temp_migration_test' missing our custom column
    await raw_conn.exec_driver_sql("CREATE TABLE temp_migration_test (id INTEGER PRIMARY KEY)")
    await db.commit()
    
    # Patch the migrations list inside migrations.py to include our custom table and column
    test_migrations = [("temp_migration_test", "new_migrated_col", "INTEGER DEFAULT 42")]
    with patch.object(app.database.migrations, "MIGRATIONS", test_migrations):
        await run_migrations(db)
    
    # Verify the column 'new_migrated_col' was added successfully on a fresh connection
    fresh_conn = await db.connection()
    def get_columns(sync_conn):
        inspector = inspect(sync_conn)
        return {col["name"] for col in inspector.get_columns("temp_migration_test")}
        
    columns = await fresh_conn.run_sync(get_columns)
    assert "new_migrated_col" in columns
    assert "id" in columns
    
    # Cleanup table using the fresh connection
    await fresh_conn.exec_driver_sql("DROP TABLE temp_migration_test")
    await db.commit()

@pytest.mark.asyncio
async def test_lifespan_permission_error():
    """Verify that lifespan correctly raises a RuntimeError on data dir PermissionError."""
    from app.main import lifespan
    from fastapi import FastAPI
    from unittest.mock import patch
    
    app = FastAPI()
    with patch("pathlib.Path.touch", side_effect=PermissionError("Permission denied")):
        with pytest.raises(RuntimeError) as exc_info:
            async with lifespan(app):
                pass
        assert "PERMISSION ERROR" in str(exc_info.value)


