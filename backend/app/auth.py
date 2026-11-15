import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

COOKIE_NAME = "tidy_session"
SESSION_SECONDS = 7 * 24 * 60 * 60


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt, digest = stored.split(":")
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)).split(":")[1], digest)


def _user(username: str, en: str, fa: str, initials_en: str, initials_fa: str, password: str | None = None):
    return {
        "username": username,
        "name": {"en": en, "fa": fa},
        "initials": {"en": initials_en, "fa": initials_fa},
        "password_hash": hash_password(password) if password else None,
    }


# Kept in memory until the database arrives (Part 6). Only "user" can sign in;
# the other team members have no password.
USERS = {
    u["username"]: u
    for u in [
        _user("user", "Atefe Kalamati", "عاطفه کلماتی", "AK", "عک", password="password"),
        _user("ali", "Ali Rezaei", "علی رضایی", "AR", "عر"),
        _user("maryam", "Maryam Karimi", "مریم کریمی", "MK", "مک"),
        _user("reza", "Reza Mohammadi", "رضا محمدی", "RM", "رم"),
    ]
}

# token -> (username, expires at, as time.time())
SESSIONS: dict[str, tuple[str, float]] = {}


def public_user(user: dict) -> dict:
    return {k: user[k] for k in ("username", "name", "initials")}


def current_user(tidy_session: str | None = Cookie(default=None)) -> dict:
    session = SESSIONS.get(tidy_session or "")
    if not session or session[1] < time.time():
        SESSIONS.pop(tidy_session or "", None)
        raise HTTPException(status_code=401, detail="Not signed in")
    return USERS[session[0]]


class Credentials(BaseModel):
    username: str
    password: str


router = APIRouter(prefix="/api")


@router.post("/login")
def login(credentials: Credentials, response: Response):
    user = USERS.get(credentials.username)
    if not user or not user["password_hash"] or not verify_password(credentials.password, user["password_hash"]):
        # One message for both cases, so it does not reveal which part was wrong.
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = (user["username"], time.time() + SESSION_SECONDS)
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax", path="/")
    return public_user(user)


@router.post("/logout", status_code=204)
def logout(response: Response, tidy_session: str | None = Cookie(default=None), _user: dict = Depends(current_user)):
    SESSIONS.pop(tidy_session or "", None)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return public_user(user)
