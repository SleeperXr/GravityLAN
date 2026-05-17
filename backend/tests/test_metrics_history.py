import pytest
from datetime import datetime, timedelta, timezone
from app.models.device import Device
from app.models.agent import DeviceMetrics, AgentToken
from app.models.setting import Setting
import json

@pytest.mark.asyncio
async def test_invalid_range_validation(client, db):
    """Verify that passing an invalid range returns 400 Bad Request."""
    # Set setup complete and master token
    token = "test-token"
    db.add(Setting(key="setup.complete", value="true"))
    db.add(Setting(key="api.master_token", value=token))
    await db.commit()

    # Call metrics endpoint with an invalid range
    headers = {"Cookie": f"session={token}"}
    response = await client.get("/api/agent/metrics/1?range=invalid", headers=headers)
    assert response.status_code == 400
    assert "Invalid range" in response.json()["detail"]


@pytest.mark.asyncio
async def test_metrics_legacy_compatibility(client, db):
    """Verify that calling without range returns the last N records chronologically (legacy behavior)."""
    # 1. Setup Auth and Setup Complete
    token = "test-token"
    db.add(Setting(key="setup.complete", value="true"))
    db.add(Setting(key="api.master_token", value=token))

    # 2. Add test device and metrics
    device = Device(id=10, ip="192.168.1.10", hostname="test-agent")
    db.add(device)
    
    now = datetime.now(timezone.utc)
    for i in range(10):
        # Add 10 metric records in reverse order
        metric = DeviceMetrics(
            device_id=10,
            cpu_percent=10.0 + i,
            ram_used_mb=1000 + i,
            ram_total_mb=8000,
            ram_percent=12.5,
            disk_json=json.dumps([{"path": "/", "total_gb": 100.0, "used_gb": 10.0, "percent": 10.0}]),
            net_json=json.dumps({"eth0": {"rx": 1000, "tx": 1000}}),
            temperature=40.0 + i,
            timestamp=now - timedelta(minutes=i)
        )
        db.add(metric)
    await db.commit()

    # 3. Request legacy metrics with limit=5
    headers = {"Cookie": f"session={token}"}
    response = await client.get("/api/agent/metrics/10?limit=5", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["device_id"] == 10
    assert data["retention_days"] == 30
    assert data["available_ranges"] == ["6h", "24h", "7d", "30d"]
    
    # Legacy returns limit (5) snapshots
    snapshots = data["snapshots"]
    assert len(snapshots) == 5
    
    # Chronological check: the first snapshot in list should be the oldest of the limit
    # and the last snapshot should be the newest (cpu_percent of oldest is 10.0 + 4 = 14.0, newest is 10.0)
    assert snapshots[0]["cpu_percent"] == 14.0
    assert snapshots[-1]["cpu_percent"] == 10.0


@pytest.mark.asyncio
async def test_metrics_aggregation_6h_range(client, db):
    """Verify aggregation downsampling for 6h range (5-minute buckets)."""
    # 1. Setup Auth and Setup Complete
    token = "test-token"
    db.add(Setting(key="setup.complete", value="true"))
    db.add(Setting(key="api.master_token", value=token))

    # 2. Add test device
    device = Device(id=20, ip="192.168.1.20", hostname="test-agent-20")
    db.add(device)

    # 3. Add metrics spanning different 5-minute buckets
    # Use a fixed base time aligned to 5-minute interval to prevent clock-based flakiness
    base_time = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)
    
    # Bucket 1: between 10m and 5m ago
    t1 = base_time - timedelta(minutes=8)
    t2 = base_time - timedelta(minutes=7)
    
    # Bucket 2: between 15m and 10m ago
    t3 = base_time - timedelta(minutes=13)
    t4 = base_time - timedelta(minutes=12)

    metrics = [
        # Bucket 1 points (Expected average: CPU=20.0, RAM=30.0, Temp=50.0)
        DeviceMetrics(device_id=20, cpu_percent=10.0, ram_used_mb=2000, ram_total_mb=8000, ram_percent=25.0, temperature=45.0, timestamp=t1, disk_json="[]", net_json="{}"),
        DeviceMetrics(device_id=20, cpu_percent=30.0, ram_used_mb=2800, ram_total_mb=8000, ram_percent=35.0, temperature=55.0, timestamp=t2, disk_json="[]", net_json="{}"),
        
        # Bucket 2 points (Expected average: CPU=40.0, RAM=50.0, Temp=70.0)
        DeviceMetrics(device_id=20, cpu_percent=35.0, ram_used_mb=3600, ram_total_mb=8000, ram_percent=45.0, temperature=65.0, timestamp=t3, disk_json="[]", net_json="{}"),
        DeviceMetrics(device_id=20, cpu_percent=45.0, ram_used_mb=4400, ram_total_mb=8000, ram_percent=55.0, temperature=75.0, timestamp=t4, disk_json="[]", net_json="{}"),
    ]
    for m in metrics:
        db.add(m)
    await db.commit()

    # 4. Request 6h aggregation
    headers = {"Cookie": f"session={token}"}
    response = await client.get("/api/agent/metrics/20?range=6h", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["retention_days"] == 30
    assert data["available_ranges"] == ["6h", "24h", "7d", "30d"]
    
    snapshots = data["snapshots"]
    # Should yield exactly 2 aggregated snapshots since other buckets are empty and skipped
    assert len(snapshots) == 2
    
    # Verify the chronological ordering of the aggregated buckets
    # Oldest bucket (Bucket 2, ~15m ago) should be first
    assert snapshots[0]["cpu_percent"] == 40.0
    assert snapshots[0]["ram"]["percent"] == 50.0
    assert snapshots[0]["temperature"] == 70.0

    # Newest bucket (Bucket 1, ~10m ago) should be second
    assert snapshots[1]["cpu_percent"] == 20.0
    assert snapshots[1]["ram"]["percent"] == 30.0
    assert snapshots[1]["temperature"] == 50.0


@pytest.mark.asyncio
async def test_metrics_aggregation_empty_buckets_skipped(client, db):
    """Verify that buckets with no metrics are completely skipped (sparse data optimization)."""
    # 1. Setup Auth and Setup Complete
    token = "test-token"
    db.add(Setting(key="setup.complete", value="true"))
    db.add(Setting(key="api.master_token", value=token))

    # 2. Add test device
    device = Device(id=30, ip="192.168.1.30", hostname="test-agent-30")
    db.add(device)

    # 3. Add two points separated by 3 hours (inside a 24h range where bucket is 15 minutes)
    now = datetime.now(timezone.utc)
    t1 = now - timedelta(hours=5)
    t2 = now - timedelta(hours=2)

    db.add(DeviceMetrics(device_id=30, cpu_percent=10.0, ram_used_mb=2000, ram_total_mb=8000, ram_percent=25.0, timestamp=t1, disk_json="[]", net_json="{}"))
    db.add(DeviceMetrics(device_id=30, cpu_percent=20.0, ram_used_mb=3000, ram_total_mb=8000, ram_percent=37.5, timestamp=t2, disk_json="[]", net_json="{}"))
    await db.commit()

    # 4. Request 24h range (15-minute buckets)
    headers = {"Cookie": f"session={token}"}
    response = await client.get("/api/agent/metrics/30?range=24h", headers=headers)
    assert response.status_code == 200
    snapshots = response.json()["snapshots"]
    # Should only return 2 snapshots instead of 96 buckets (since other 94 intervals were offline/empty)
    assert len(snapshots) == 2
    assert snapshots[0]["cpu_percent"] == 10.0
    assert snapshots[1]["cpu_percent"] == 20.0


@pytest.mark.asyncio
async def test_metrics_db_retention_override(client, db):
    """Verify that when history_retention_days is configured in the database, the API returns the DB value and limits ranges accordingly."""
    # 1. Setup Auth and Setup Complete
    token = "test-token"
    db.add(Setting(key="setup.complete", value="true"))
    db.add(Setting(key="api.master_token", value=token))
    
    # Configure 5-day retention in database override
    db.add(Setting(key="history_retention_days", value="5"))
    await db.commit()
    
    # 2. Add device
    device = Device(id=40, ip="192.168.1.40", hostname="test-agent-40")
    db.add(device)
    await db.commit()
    
    # 3. Call metrics history endpoint
    headers = {"Cookie": f"session={token}"}
    response = await client.get("/api/agent/metrics/40", headers=headers)
    assert response.status_code == 200
    data = response.json()
    
    # 4. Assertions: Should return DB setting value (5) and range constraints based on 5 days (no 7d or 30d!)
    assert data["retention_days"] == 5
    assert data["available_ranges"] == ["6h", "24h"]  # 7d and 30d are excluded because 5 < 7
