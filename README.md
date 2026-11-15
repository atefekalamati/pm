# Tidy

A bilingual (English / Persian) Kanban project board with an AI assistant. Next.js frontend, FastAPI backend, SQLite, all in one Docker container.

## Run

Requires Docker Desktop (Windows: with WSL2).

1. Optional, for AI: copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`. `AI_BASE_URL` and `AI_MODEL` choose the service; any OpenAI-compatible one works (OpenRouter by default, or for example Google AI Studio: `https://generativelanguage.googleapis.com/v1beta/openai/` with a Gemini model). With the app running, `POST /api/ai/test` in http://localhost:8000/docs checks the connection.
2. Start: `scripts/start.sh` (Mac / Linux) or `scripts\start.ps1` (Windows).
3. Open http://localhost:8000
4. Stop: `scripts/stop.sh` or `scripts\stop.ps1`. The database volume is kept.

## Tests

- Backend: `cd backend && uv run pytest`
- Frontend: `cd frontend && npm test && npx playwright test` (the Playwright run starts its own test backend; see `frontend/AGENTS.md` for testing the Docker container)

API docs (while it runs): http://localhost:8000/docs. The database is `/data/tidy.db` on the `tidy-data` Docker volume, so it survives restarts.

Plan and progress: `docs/PLAN.md`; database design: `docs/DATABASE.md`.
