@echo off
REM Usage: start-immich-cpu.bat       ^> prebuilt images from GHCR (default)
REM        start-immich-cpu.bat dev   ^> build backend/frontend from source (repo clone)
pushd "%~dp0.."
echo Starting MyVault + Immich (CPU)...
if /i "%~1"=="dev" (
  echo Building from local source...
  docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile immich up -d --build
) else (
  echo Pulling app images from GHCR when needed...
  docker compose pull backend frontend
  docker compose --profile immich up -d
)
echo.
echo App:   http://localhost:5173
echo Immich:http://localhost:2283
popd
pause
