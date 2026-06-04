#!/usr/bin/env bash
set -euo pipefail
# Usage: ./start-immich-cpu.sh       → prebuilt images from GHCR (default)
#        ./start-immich-cpu.sh dev   → build backend/frontend from source (repo clone)

cd "$(dirname "$0")/.."

echo "Starting MyVault + Immich (CPU)..."
if [[ "${1:-}" == "dev" ]]; then
  echo "Building from local source..."
  docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile immich up -d --build
else
  echo "Pulling app images from GHCR (if needed)..."
  docker compose pull backend frontend
  docker compose --profile immich up -d
fi

echo
echo "App:   http://localhost:5173"
echo "Immich:http://localhost:2283"
