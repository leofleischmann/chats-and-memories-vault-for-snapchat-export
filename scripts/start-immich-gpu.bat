@echo off
REM Usage: start-immich-gpu.bat       ^> prebuilt images from GHCR (default)
REM        start-immich-gpu.bat dev   ^> build backend/frontend from source (repo clone)
pushd "%~dp0.."
echo Starting MyVault + Immich (GPU / NVIDIA CUDA)...
echo Note: NVIDIA driver + Container Toolkit must be installed.
if /i "%~1"=="dev" (
  echo Building from local source...
  docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.backend-gpu.yml --profile immich-gpu up -d --build
) else (
  echo Pulling app images from GHCR when needed...
  docker compose pull backend frontend
  docker compose -f docker-compose.yml -f docker-compose.backend-gpu.yml --profile immich-gpu up -d
)
echo.
echo App:   http://localhost:5173
echo Immich:http://localhost:2283
popd
pause
