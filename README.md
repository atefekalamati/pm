# Tidy

A bilingual (English / Persian) Kanban project board with an AI assistant. Next.js frontend, FastAPI backend, SQLite, all in one Docker container.

## Run

Requires **Docker Desktop** (Windows: with WSL2). Nothing else needs to be installed.

1. **Optional, for the AI assistant:** copy `.env.example` to `.env` (in the project root) and put your key in `OPENROUTER_API_KEY`. Without it everything else works and the assistant says "AI is not configured". `.env` is never committed.
2. **Start:** `scripts\start.ps1` (Windows, PowerShell) or `scripts/start.sh` (Mac / Linux). The first start builds the image and takes a few minutes. It prints `Tidy is running at http://localhost:8000`.
3. **Open** http://localhost:8000 and sign in with:

   | Username | Password |
   |---|---|
   | `user` | `password` |

4. **Stop:** `scripts\stop.ps1` or `scripts/stop.sh`. Your data is kept: it lives in the Docker volume `tidy-data` (`/data/tidy.db` in the container), so it survives stopping, restarting and rebuilding. After changing `.env`, stop and start again.

API documentation and a way to try every route: http://localhost:8000/docs (sign in with `POST /api/login` first).

## AI assistant

Open it from the sidebar ("AI assistant", or press `A`). It can create cards, edit them and move them between columns, and it answers in the language you write in.

Three variables in `.env` choose the service. Any service with an OpenAI-compatible API works:

| Variable | Meaning | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | the API key (required) | none |
| `AI_BASE_URL` | the service's OpenAI-compatible address | `https://openrouter.ai/api/v1` |
| `AI_MODEL` | the model name that service expects | `openai/gpt-oss-120b` |

**To change the model:** edit `AI_MODEL` and restart (`stop` then `start`). **To change the provider:** change all three. For example, Google AI Studio:

```
OPENROUTER_API_KEY=<your Google AI Studio key>
AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
AI_MODEL=gemini-3.5-flash-lite
```

The variable is still called `OPENROUTER_API_KEY` whatever the provider. To see the model names a service offers, open `<AI_BASE_URL>models` with your key (for Google: `GET https://generativelanguage.googleapis.com/v1beta/openai/models` with the header `Authorization: Bearer <key>`). To check the connection: in http://localhost:8000/docs run `POST /api/ai/test`; it should answer `4`. A busy or rate-limited service shows a message in the panel with a "Try again" button; the model name or the provider can be changed at any time.

## Tests

- Backend: `cd backend && uv run pytest` (needs [uv](https://docs.astral.sh/uv/)). Uses mocks; one test calls the real AI service, only if a key exists in `.env`.
- Frontend: `cd frontend && npm test && npx playwright test` (the Playwright run starts its own test backend; see `frontend/AGENTS.md` for testing the Docker container).

Plan and progress: `docs/PLAN.md`. Database design: `docs/DATABASE.md`.
