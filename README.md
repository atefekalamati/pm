# Tidy

A bilingual (English / Persian) Kanban project board with an AI assistant. Next.js frontend, FastAPI backend, SQLite, all in one Docker container.

## Run

Requires Docker Desktop (Windows: with WSL2).

1. Optional, for AI: copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`.
2. Start: `scripts/start.sh` (Mac / Linux) or `scripts\start.ps1` (Windows).
3. Open http://localhost:8000
4. Stop: `scripts/stop.sh` or `scripts\stop.ps1`. The database volume is kept.

## Tests

- Backend: `cd backend && uv run pytest`
- Frontend: `cd frontend && npm test && npx playwright test`

Plan and progress: `docs/PLAN.md`.
