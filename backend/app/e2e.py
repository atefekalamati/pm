"""Test-only helper, registered only when the server starts with TIDY_E2E=1 (never in a normal run).

Playwright tests share one server, so each test makes its own user: a new user with the password `password`,
named like the sample user, and a fresh sample board whose dates are counted from `today`. Nothing else is shared.
"""

import sqlite3
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import get_db, new_id, now_iso, tx
from app.security import hash_password
from app.seed import create_board

router = APIRouter(prefix="/api/e2e")


class NewUser(BaseModel):
    username: str
    today: date | None = None  # the "today" of the sample data (default: now)


@router.post("/users", status_code=201)
def create_user(body: NewUser, conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (body.username,)).fetchone():
        raise HTTPException(status_code=409, detail="That username exists")
    user_id = new_id()
    with tx(conn):
        conn.execute(
            "INSERT INTO users (id, username, password_hash, name, name_fa, initials, initials_fa, created_at) VALUES (?, ?, ?, 'Atefe Kalamati', ?, 'AK', ?, ?)",
            (user_id, body.username, hash_password("password"), "عاطفه کلماتی", "عک", now_iso()),
        )
    now = datetime.combine(body.today, time(11, 0), tzinfo=timezone.utc) if body.today else None
    create_board(conn, user_id, now)
    return {"username": body.username, "password": "password"}
