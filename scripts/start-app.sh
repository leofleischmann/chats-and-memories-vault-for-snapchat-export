#!/usr/bin/env bash
set -euo pipefail
# Usage: ./start-app.sh       → prebuilt images from GHCR (default)
#        ./start-app.sh dev   → build backend/frontend from source (repo clone)

cd "$(dirname "$0")/.."

echo "Starting MyVault (without Immich)..."
if [[ "${1:-}" == "dev" ]]; then
  echo "Building from local source..."
  docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
else
  echo "Pulling app images from GHCR (if needed)..."
  docker compose pull backend frontend
  docker compose up -d
fi

echo
echo "App: http://localhost:5173"
