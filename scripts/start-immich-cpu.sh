#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Starting MyVault + Immich (CPU)..."
docker compose --profile immich up -d --build

echo
echo "App:   http://localhost:5173"
echo "Immich: http://localhost:2283"

