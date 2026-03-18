@echo off
cd /d "%~dp0"
echo Starte SnapChats + Immich (GPU / NVIDIA CUDA)...
echo Hinweis: NVIDIA Treiber + Container Toolkit muessen installiert sein.
docker compose --profile immich-gpu up -d --build
echo.
echo App:   http://localhost:5173
echo Immich:http://localhost:2283
pause
