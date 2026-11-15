# Backend

FastAPI app, packages managed with `uv` (`pyproject.toml`, `uv.lock`).

- `app/main.py`: the app. `GET /api/health` returns `{"status": "ok"}` and stays public (Docker health check and the start scripts use it). `static/` is mounted at `/` last, so `/api` routes take precedence.
- `static/`: files served at `/` (path can be changed with `STATIC_DIR`). In Docker this is the Next.js static export copied from `frontend/out`; it is a build output and not in git.
- `tests/`: pytest with FastAPI `TestClient`. `conftest.py` points `STATIC_DIR` at a small temporary page, so no frontend build is needed. Run `uv run pytest` in this folder.

The `Dockerfile` builds the frontend in a Node stage, then copies `out/` into this image. In Docker the app runs with `uvicorn app.main:app` on port 8000. `DATABASE_PATH` is `/data/tidy.db` on the `tidy-data` volume; `.env` is read at run time by `docker-compose.yml` and never copied into the image.
