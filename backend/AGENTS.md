# Backend

FastAPI app, packages managed with `uv` (`pyproject.toml`, `uv.lock`).

- `app/main.py`: the app. `GET /api/health` returns `{"status": "ok"}` and stays public (Docker health check and the start scripts use it). `static/` is mounted at `/` last, so `/api` routes take precedence.
- `app/auth.py`: sign-in. Users are in memory for now (moved to SQLite in Part 6): `user` / `password` (Atefe Kalamati, scrypt hash) and three team members without a password, who cannot sign in. `POST /api/login` sets an HttpOnly, SameSite=Lax cookie `tidy_session` (7 days, in-memory sessions, so a restart signs out); a wrong username or password gets one generic `401`. `POST /api/logout`, `GET /api/me`. Protect new routes with `Depends(current_user)`; only login and `/api/health` are public.
- API answers carry `Cache-Control: no-store`.
- `static/`: files served at `/` (path can be changed with `STATIC_DIR`). In Docker this is the Next.js static export copied from `frontend/out`; it is a build output and not in git.
- `tests/`: pytest with FastAPI `TestClient`. `conftest.py` points `STATIC_DIR` at a small temporary page, so no frontend build is needed. Run `uv run pytest` in this folder.

The `Dockerfile` builds the frontend in a Node stage, then copies `out/` into this image. In Docker the app runs with `uvicorn app.main:app` on port 8000. `DATABASE_PATH` is `/data/tidy.db` on the `tidy-data` volume; `.env` is read at run time by `docker-compose.yml` and never copied into the image.
