@echo off
REM Usage: start-app.bat       ^> prebuilt images from GHCR (default)
REM        start-app.bat dev   ^> build backend/frontend from source (repo clone)
pushd "%~dp0.."
echo Starting MyVault (without Immich)...
if /i "%~1"=="dev" (
  echo Building from local source...
  docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
) else (
  echo Pulling app images from GHCR when needed...
  docker compose pull backend frontend
  docker compose up -d
)
echo.
echo App: http://localhost:5173
popd
pause
