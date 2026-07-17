import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import status
from app.models.device import Device
from app.models.agent import AgentToken
from app.services.patch_service import list_device_updates, run_ssh_command_stream

# Test data for mocked SSH outputs
APT_UPGRADABLE_MOCK = """
Listing... Done
curl/jammy-updates 7.81.0-1ubuntu1.16 amd64 [upgradable from: 7.81.0-1ubuntu1.15]
libssl3/jammy-updates 3.0.2-0ubuntu1.15 amd64 [upgradable from: 3.0.2-0ubuntu1.14]
"""

DNF_CHECK_UPDATE_MOCK = """
Last metadata expiration check: 0:15:32 ago on Fri Jul 17 09:00:00 2026.

curl.x86_64               7.81.0-1.fc39             updates
libssl.x86_64             3.0.2-1.fc39              updates
"""

RPM_Q_MOCK = """
curl 7.81.0-1.fc38
libssl 3.0.2-1.fc38
"""

@pytest.mark.asyncio
@patch("paramiko.SSHClient")
async def test_list_device_updates_apt(mock_ssh_client):
    # Setup mocks
    client_instance = MagicMock()
    mock_ssh_client.return_value = client_instance
    
    # 1. which apt-get output
    mock_chan_which = MagicMock()
    mock_chan_which.read.return_value = b"/usr/bin/apt-get"
    
    # 2. apt-get update channel
    mock_chan_update = MagicMock()
    mock_chan_update.exit_status_ready.return_value = True
    
    # 3. apt list --upgradable output
    mock_chan_list = MagicMock()
    mock_chan_list.read.return_value = APT_UPGRADABLE_MOCK.encode("utf-8")
    
    # 4. which do-release-upgrade (major release upgrade check)
    mock_chan_do_release = MagicMock()
    mock_chan_do_release.read.return_value = b"/usr/bin/do-release-upgrade"
    
    # 5. do-release-upgrade -c output
    mock_chan_release_c = MagicMock()
    mock_chan_release_c.read.return_value = b"New release '24.04 LTS' available."

    # Return different mocks for consecutive exec_command calls
    client_instance.exec_command.side_effect = [
        (None, mock_chan_which, None),
        (None, mock_chan_list, None),
        (None, mock_chan_do_release, None),
        (None, mock_chan_release_c, None),
    ]
    
    # Mock transport and update channel
    mock_transport = MagicMock()
    client_instance.get_transport.return_value = mock_transport
    mock_transport.open_session.return_value = mock_chan_update
    
    res = await list_device_updates(
        host_ip="192.168.1.100",
        ssh_user="root",
        ssh_password="password",
        ssh_port=22
    )
    
    assert res["patch_manager"] == "apt"
    assert len(res["packages"]) == 2
    assert res["packages"][0]["package"] == "curl"
    assert res["packages"][0]["current_version"] == "7.81.0-1ubuntu1.15"
    assert res["packages"][0]["new_version"] == "7.81.0-1ubuntu1.16"
    assert res["major_upgrade_available"] == "24.04 LTS"


@pytest.mark.asyncio
@patch("paramiko.SSHClient")
async def test_list_device_updates_dnf(mock_ssh_client):
    client_instance = MagicMock()
    mock_ssh_client.return_value = client_instance
    
    # 1. which dnf
    mock_chan_which = MagicMock()
    mock_chan_which.read.return_value = b"/usr/bin/dnf"
    
    # 2. dnf check-update output
    mock_chan_check = MagicMock()
    mock_chan_check.read.return_value = DNF_CHECK_UPDATE_MOCK.encode("utf-8")
    
    # 3. rpm -q query
    mock_chan_rpm = MagicMock()
    mock_chan_rpm.read.return_value = RPM_Q_MOCK.encode("utf-8")
    
    client_instance.exec_command.side_effect = [
        (None, mock_chan_which, None),
        (None, mock_chan_check, None),
        (None, mock_chan_rpm, None),
    ]
    
    res = await list_device_updates(
        host_ip="192.168.1.101",
        ssh_user="root",
        ssh_password="password",
        ssh_port=22
    )
    
    assert res["patch_manager"] == "dnf"
    assert len(res["packages"]) == 2
    assert res["packages"][0]["package"] == "curl"
    assert res["packages"][0]["current_version"] == "7.81.0-1.fc38"
    assert res["packages"][0]["new_version"] == "7.81.0-1.fc39"


@pytest.mark.asyncio
async def test_query_device_patches_endpoint_unauthorized(client, db):
    # Setup setup.complete = true to enforce authentication
    from app.models.setting import Setting
    db.add(Setting(key="setup.complete", value="true"))
    await db.commit()

    # Verify protected endpoint returns 401
    response = await client.post("/api/agent/patches/1/query", json={
        "ssh_user": "root",
        "ssh_password": "password"
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_prepare_patch_action_endpoint_authorized(client, db, admin_token):
    # Setup a dummy device in DB
    device = Device(ip="192.168.1.100", display_name="Test agent device")
    db.add(device)
    await db.commit()
    await db.refresh(device)
    
    response = await client.post(
        f"/api/agent/patches/{device.id}/prepare",
        json={
            "ssh_user": "root",
            "ssh_password": "password",
            "mode": "upgrade"
        },
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "patch_token" in data
    assert data["patch_token"].startswith("patch_tok_")
