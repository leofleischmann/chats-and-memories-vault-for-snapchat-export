@echo off
cd /d "%~dp0"
echo Stopping all containers (including Immich)...
docker compose --profile immich --profile immich-gpu down
echo.
pause
