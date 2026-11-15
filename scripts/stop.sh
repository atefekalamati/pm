#!/usr/bin/env sh
# Stops Tidy and removes its container (Mac and Linux). The database volume is kept.
cd "$(dirname "$0")/.." || exit 1
docker compose down || exit 1
echo "Tidy has stopped."
