# Backend

FastAPI app, packages managed with `uv` (`pyproject.toml`, `uv.lock`).

- `app/main.py`: the app. `GET /api/health` returns `{"status": "ok"}` and stays public (Docker health check and the start scripts use it). `static/` is mounted at `/` last, so `/api` routes take precedence.
- `static/`: files served at `/`. For now a Hello World page that calls `/api/health`; from Part 3 the Next.js static export.
- `tests/`: pytest with FastAPI `TestClient`. Run `uv run pytest` in this folder.

In Docker the app runs with `uvicorn app.main:app` on port 8000. `DATABASE_PATH` is `/data/tidy.db` on the `tidy-data` volume; `.env` is read at run time by `docker-compose.yml` and never copied into the image.
