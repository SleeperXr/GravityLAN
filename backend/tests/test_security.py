import pytest
from app.services.auth_service import hash_password, verify_password, looks_hashed, secure_compare

def test_password_hashing():
    password = "secret_password_123"
    hashed = hash_password(password)
    
    assert hashed != password
    assert looks_hashed(hashed)
    assert verify_password(password, hashed)
    assert not verify_password("wrong_password", hashed)

def test_looks_hashed():
    assert looks_hashed("$2b$12$somehash")
    assert looks_hashed("$argon2id$v=19$m=65536,t=3,p=4$somehash")
    assert not looks_hashed("plaintext")
    assert not looks_hashed("12345678")

def test_secure_compare():
    assert secure_compare("abc", "abc")
    assert not secure_compare("abc", "abd")
    assert not secure_compare("abc", "")
    assert not secure_compare(None, "abc")

@pytest.mark.asyncio
async def test_login_no_token_leak(client, db):
    """Verify that login response does not contain the master token."""
    from app.models.setting import Setting
    from app.services.auth_service import hash_password
    
    # 1. Prepare DB
    db.add(Setting(key="setup.complete", value="true", category="system"))
    db.add(Setting(key="api.master_token", value="master_secret_token", category="system"))
    db.add(Setting(key="api.admin_password", value=hash_password("admin123"), category="system"))
    await db.commit()
    
    # 2. Login
    response = await client.post("/api/auth/login", json={"password": "admin123"})
    assert response.status_code == 200
    data = response.json()
    
    # 3. Check for leaks
    assert "token" not in data
    assert "master_secret_token" not in response.text
    # Check if cookie is set
    assert "gravitylan_token" in response.cookies

@pytest.mark.asyncio
async def test_setup_idempotency(client, db):
    """Verify that mark_setup_complete fails if setup is already done."""
    from app.models.setting import Setting
    db.add(Setting(key="setup.complete", value="true", category="system"))
    await db.commit()
    
    response = await client.post("/api/setup/complete", json={"admin_password": "new_password"})
    assert response.status_code == 400
    assert "Setup already completed" in response.json()["detail"]

def test_config_settings_defaults():
    """Verify default values for new SSH strict mode and retention configurations."""
    from app.config import settings
    assert settings.ssh_strict_mode is False
    assert settings.history_retention_days == 30

@pytest.mark.asyncio
async def test_clean_old_history_and_metrics(db):
    """Verify ScanScheduler._clean_old_history successfully prunes DeviceHistory and DeviceMetrics."""
    from datetime import datetime, timezone, timedelta
    from app.models.device import Device, DeviceHistory
    from app.models.agent import DeviceMetrics
    from app.scanner.scheduler import ScanScheduler
    from app.models.setting import Setting

    # 1. Add base device
    dev = Device(
        ip="192.168.100.10",
        mac="00:11:22:33:44:55",
        hostname="test-host",
        is_online=True,
    )
    db.add(dev)
    await db.commit()
    await db.refresh(dev)

    # 2. Add old and new history entries (retention configured as 5 days in settings)
    db.add(Setting(key="history_retention_days", value="5", category="system"))
    
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=6)
    new_time = now - timedelta(days=2)

    # Convert to naive datetime as stored in the models
    old_naive = old_time.replace(tzinfo=None)
    new_naive = new_time.replace(tzinfo=None)

    hist_old = DeviceHistory(device_id=dev.id, status="offline", timestamp=old_naive)
    hist_new = DeviceHistory(device_id=dev.id, status="online", timestamp=new_naive)

    # Also add DeviceMetrics
    metrics_old = DeviceMetrics(
        device_id=dev.id,
        timestamp=old_naive,
        cpu_percent=85.0,
        ram_used_mb=1024,
        ram_total_mb=2048,
        ram_percent=50.0,
        disk_json="[]",
        net_json="{}",
    )
    metrics_new = DeviceMetrics(
        device_id=dev.id,
        timestamp=new_naive,
        cpu_percent=12.0,
        ram_used_mb=512,
        ram_total_mb=2048,
        ram_percent=25.0,
        disk_json="[]",
        net_json="{}",
    )

    db.add_all([hist_old, hist_new, metrics_old, metrics_new])
    await db.commit()

    # 3. Instantiate and run ScanScheduler._clean_old_history
    import app.scanner.scheduler
    from unittest.mock import patch

    class TestSessionContext:
        async def __aenter__(self):
            return db
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    scheduler_instance = ScanScheduler()
    with patch("app.scanner.scheduler.async_session", TestSessionContext):
        await scheduler_instance._clean_old_history(force=True)

    # 4. Assertions
    from sqlalchemy import select
    res_hist = await db.execute(select(DeviceHistory))
    histories = res_hist.scalars().all()
    assert len(histories) == 1
    assert histories[0].status == "online"

    res_met = await db.execute(select(DeviceMetrics))
    metrics = res_met.scalars().all()
    assert len(metrics) == 1
    assert metrics[0].cpu_percent == 12.0

def test_config_settings_validation():
    """Verify validation constraints for config settings."""
    from app.config import Settings
    from pydantic import ValidationError
    
    # Valid configurations
    s = Settings(history_retention_days=10)
    assert s.history_retention_days == 10
    
    # Invalid history retention (below 1)
    with pytest.raises(ValidationError):
        Settings(history_retention_days=0)
        
    # Invalid history retention (above 365)
    with pytest.raises(ValidationError):
        Settings(history_retention_days=366)

@pytest.mark.asyncio
async def test_ssh_strict_mode_policies():
    """Verify that deploy_agent uses the correct SSH host key policy based on settings."""
    from unittest.mock import patch, MagicMock
    from app.services.agent_deployer import deploy_agent, remove_agent
    from app.config import settings
    import paramiko

    # Mock SSHClient
    mock_client = MagicMock()
    with patch("paramiko.SSHClient", return_value=mock_client):
        # 1. Test deploy_agent with Strict Mode = True
        with patch.object(settings, "ssh_strict_mode", True):
            # We mock the connect/exec to raise/return immediately so we don't block
            mock_client.connect.side_effect = Exception("Stop execution")
            await deploy_agent(
                host_ip="192.168.1.100",
                ssh_user="test",
                ssh_password="password",
                server_url="http://localhost:8000",
                device_id=1,
            )
            args, _ = mock_client.set_missing_host_key_policy.call_args
            assert isinstance(args[0], paramiko.RejectPolicy)
            mock_client.load_system_host_keys.assert_called_once()
            
        mock_client.reset_mock()

        # 2. Test deploy_agent with Strict Mode = False
        with patch.object(settings, "ssh_strict_mode", False):
            mock_client.connect.side_effect = Exception("Stop execution")
            await deploy_agent(
                host_ip="192.168.1.100",
                ssh_user="test",
                ssh_password="password",
                server_url="http://localhost:8000",
                device_id=1,
            )
            args, _ = mock_client.set_missing_host_key_policy.call_args
            assert isinstance(args[0], paramiko.WarningPolicy)
            assert not mock_client.load_system_host_keys.called

        mock_client.reset_mock()

        # 3. Test remove_agent with Strict Mode = True
        with patch.object(settings, "ssh_strict_mode", True):
            mock_client.connect.side_effect = Exception("Stop execution")
            await remove_agent(
                host_ip="192.168.1.100",
                ssh_user="test",
                ssh_password="password",
            )
            args, _ = mock_client.set_missing_host_key_policy.call_args
            assert isinstance(args[0], paramiko.RejectPolicy)
            mock_client.load_system_host_keys.assert_called_once()
