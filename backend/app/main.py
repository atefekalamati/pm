from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Tidy")


@app.get("/api/health")
def health():
    """Public on purpose: Docker and the start scripts use it to check the server is up."""
    return {"status": "ok"}


# Registered last so /api routes take precedence.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
