# Scripts

Start and stop Tidy in Docker. Both run from any folder and use `docker compose` from the project root.

- `start.sh` / `stop.sh`: Mac and Linux.
- `start.ps1` / `stop.ps1`: Windows (PowerShell, Docker Desktop with WSL2).

`start` checks that Docker is running, warns if `.env` is missing (the app then runs without AI), runs `docker compose up -d --build --wait` (which waits for the `/api/health` health check) and prints `http://localhost:8000`. `stop` runs `docker compose down`; the `tidy-data` database volume is kept.
