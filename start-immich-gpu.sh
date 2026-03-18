#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Starting MyVault + Immich (GPU / NVIDIA CUDA)..."
echo "Note: NVIDIA driver + Container Toolkit must be installed."
docker compose --profile immich-gpu up -d --build

echo
echo "App:   http://localhost:5173"
echo "Immich: http://localhost:2283"

