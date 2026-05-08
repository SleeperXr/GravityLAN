# GravityLAN Startup Script (Windows Dev)
Write-Host "Starting GravityLAN Development Stack..." -ForegroundColor Cyan

# 1. Start Backend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" -WindowStyle Normal

# 2. Start Frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev" -WindowStyle Normal

Write-Host "Backend: http://localhost:8000"
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "GravityLAN is running!" -ForegroundColor Green
