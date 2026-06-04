#!/usr/bin/env bash
set -euo pipefail
# Usage: ./start-immich-gpu.sh       → prebuilt images from GHCR (default)
#        ./start-immich-gpu.sh dev   → build backend/frontend from source (repo clone)

cd "$(dirname "$0")/.."

echo "Starting MyVault + Immich (GPU / NVIDIA CUDA)..."
echo "Note: NVIDIA driver + Container Toolkit must be installed."
if [[ "${1:-}" == "dev" ]]; then
  echo "Building from local source..."
  docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.backend-gpu.yml --profile immich-gpu up -d --build
else
  echo "Pulling app images from GHCR (if needed)..."
  docker compose pull backend frontend
  docker compose -f docker-compose.yml -f docker-compose.backend-gpu.yml --profile immich-gpu up -d
fi

echo
echo "App:   http://localhost:5173"
echo "Immich:http://localhost:2283"
