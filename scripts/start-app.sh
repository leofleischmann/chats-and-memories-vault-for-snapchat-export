#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Starting MyVault (without Immich)..."
docker compose up -d --build

echo
echo "App: http://localhost:5173"

