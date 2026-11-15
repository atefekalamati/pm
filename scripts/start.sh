#!/usr/bin/env sh
# Builds and starts Tidy in Docker (Mac and Linux).
cd "$(dirname "$0")/.." || exit 1

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker Desktop (or the Docker daemon) and try again."
  exit 1
fi

if [ ! -f .env ]; then
  echo "No .env file found: Tidy will run without AI. Copy .env.example to .env to enable it."
fi

docker compose up -d --build --wait || exit 1
echo "Tidy is running at http://localhost:8000"
