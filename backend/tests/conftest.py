import os
import tempfile
from pathlib import Path

import pytest

# A tiny stand-in for the frontend build, so tests do not need `npm run build`.
_static = Path(tempfile.mkdtemp())
(_static / "index.html").write_text("<!DOCTYPE html><title>Tidy</title><div id='app'></div>", encoding="utf-8")
(_static / "404.html").write_text("<!DOCTYPE html><title>Not found</title>", encoding="utf-8")
os.environ["STATIC_DIR"] = str(_static)

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402


@pytest.fixture(autouse=True)
def no_ai_in_the_environment(monkeypatch):
    """No test reaches a real AI service by accident: the AI variables are cleared, and tests set what they need."""
    for name in ("OPENROUTER_API_KEY", "AI_BASE_URL", "AI_MODEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """The AI retry waits 2 seconds; tests record the wait instead of sleeping."""
    from types import SimpleNamespace

    from app import ai

    waited: list[float] = []
    monkeypatch.setattr(ai, "time", SimpleNamespace(sleep=waited.append))
    return waited


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    """A fresh database file for every test (created by the app at startup)."""
    path = tmp_path / "tidy.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    return path


@pytest.fixture
def client(db_file):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def me(client):
    """The sample user, signed in."""
    response = client.post("/api/login", json={"username": "user", "password": "password"})
    assert response.status_code == 200
    return client


@pytest.fixture
def conn(db_file, client):
    """A second connection to the same database, for looking inside it."""
    connection = db.connect(db_file)
    yield connection
    connection.close()


@pytest.fixture
def other(client, conn):
    """A second real user with their own board, signed in on their own client."""
    conn.execute(
        "INSERT INTO users (id, username, password_hash, name, initials, created_at) VALUES (?, 'other', ?, 'Other User', 'OU', ?)",
        (db.new_id(), hash_password("secret"), db.now_iso()),
    )
    second = TestClient(app)  # the app is already started by `client`
    assert second.post("/api/login", json={"username": "other", "password": "secret"}).status_code == 200
    return second
