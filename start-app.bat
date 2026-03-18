@echo off
cd /d "%~dp0"
echo Starting MyVault (without Immich)...
docker compose up -d --build
echo.
echo App: http://localhost:5173
pause
