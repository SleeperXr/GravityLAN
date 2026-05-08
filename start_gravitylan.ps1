# GravityLAN Startup Script (Windows Dev)
Write-Host "Checking Dependencies..." -ForegroundColor Cyan

# 1. Install Backend Requirements
cd backend
Write-Host "Installing Python requirements..." -ForegroundColor Gray
pip install -e . 2>$null
if ($LASTEXITCODE -ne 0) {
    # Fallback if no pyproject.toml installable or pip -e fails
    pip install fastapi uvicorn sqlalchemy aiosqlite pydantic pydantic-settings websockets paramiko dnspython netifaces
}
cd ..

# 2. Install Frontend Requirements
cd frontend
if (!(Test-Path "node_modules")) {
    Write-Host "Installing Node.js requirements (npm install)..." -ForegroundColor Gray
    npm install
}
cd ..

Write-Host "Starting GravityLAN Development Stack..." -ForegroundColor Cyan

# 3. Start Backend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" -WindowStyle Normal

# 4. Start Frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev" -WindowStyle Normal

Write-Host "Backend: http://localhost:8000"
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "GravityLAN is running!" -ForegroundColor Green
