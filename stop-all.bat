@echo off
cd /d "%~dp0"
echo Stoppe alle Container (inkl. Immich)...
docker compose --profile immich --profile immich-gpu down
echo.
pause
