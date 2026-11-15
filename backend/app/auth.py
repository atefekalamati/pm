import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

from app.board import board_id_of, user_json
from app.db import get_db, now_iso, tx
from app.security import hash_password, hash_token, verify_password
from app.seed import create_board

COOKIE_NAME = "tidy_session"
SESSION_SECONDS = 7 * 24 * 60 * 60

# Checked for unknown users too, so a wrong username takes as long as a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password")


def public_user(row: sqlite3.Row) -> dict:
    return {**user_json(row), "username": row["username"]}


def current_user(tidy_session: str | None = Cookie(default=None), conn: sqlite3.Connection = Depends(get_db)) -> sqlite3.Row:
    row = None
    if tidy_session:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
            (hash_token(tidy_session), now_iso()),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Not signed in")
    return row


class Credentials(BaseModel):
    username: str
    password: str


router = APIRouter(prefix="/api")


@router.post("/login")
def login(credentials: Credentials, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    user = conn.execute("SELECT * FROM users WHERE username = ?", (credentials.username,)).fetchone()
    stored = user["password_hash"] if user else None
    ok = verify_password(credentials.password, stored or _DUMMY_HASH) and stored is not None
    if not ok:
        # One message for every failure, so it does not reveal which part was wrong (or that a user exists).
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = secrets.token_urlsafe(32)
    with tx(conn):
        expires = now_iso(datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS))
        conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)", (hash_token(token), user["id"], now_iso(), expires))
    if board_id_of(conn, user["id"]) is None:
        create_board(conn, user["id"])  # first sign-in: the sample board, in both languages
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax", path="/")
    return public_user(user)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    tidy_session: str | None = Cookie(default=None),
    conn: sqlite3.Connection = Depends(get_db),
    _user: sqlite3.Row = Depends(current_user),
):
    with tx(conn):
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(tidy_session or ""),))
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")


@router.get("/me")
def me(user: sqlite3.Row = Depends(current_user)):
    return public_user(user)
