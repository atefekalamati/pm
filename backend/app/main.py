import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app import api, auth, db, e2e

# The Next.js static export (frontend/out), copied here by the Dockerfile.
STATIC_DIR = Path(os.environ.get("STATIC_DIR", Path(__file__).resolve().parent.parent / "static"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Creates the database file when missing, applies migrations, adds the team users, purges old data.
    path = db.db_path()
    db.init_db(path)
    app.state.db_path = path
    yield


app = FastAPI(title="Tidy", lifespan=lifespan)


@app.middleware("http")
async def no_store_api(request: Request, call_next):
    """API answers depend on the session, so the browser must never reuse them (e.g. on Back)."""
    response = await call_next(request)
    if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    """Public on purpose: Docker and the start scripts use it to check the server is up."""
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(api.router)
if os.environ.get("TIDY_E2E") == "1":  # test servers only: lets each Playwright test create its own user
    app.include_router(e2e.router)

# Registered last so /api routes take precedence. Absent when the backend runs next to `npm run dev`.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
