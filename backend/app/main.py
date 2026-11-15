import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app import auth

# The Next.js static export (frontend/out), copied here by the Dockerfile.
STATIC_DIR = Path(os.environ.get("STATIC_DIR", Path(__file__).resolve().parent.parent / "static"))

app = FastAPI(title="Tidy")


@app.middleware("http")
async def no_store_api(request: Request, call_next):
    """API answers depend on the session, so the browser must never reuse them (e.g. on Back)."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health():
    """Public on purpose: Docker and the start scripts use it to check the server is up."""
    return {"status": "ok"}


app.include_router(auth.router)

# Registered last so /api routes take precedence. Absent when the backend runs next to `npm run dev`.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
