# GravityLAN Stop Script
Write-Host "Stopping GravityLAN processes..." -ForegroundColor Yellow

# Kill Python (Uvicorn)
Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like "*uvicorn app.main:app*"} | Stop-Process -Force

# Kill Node (Vite)
Get-Process node -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like "*vite*"} | Stop-Process -Force

Write-Host "GravityLAN stopped." -ForegroundColor Green
