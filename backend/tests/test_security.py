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
