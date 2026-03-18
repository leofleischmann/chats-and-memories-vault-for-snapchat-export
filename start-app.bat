@echo off
cd /d "%~dp0"
echo Starte SnapChats (ohne Immich)...
docker compose up -d --build
echo.
echo App: http://localhost:5173
pause
