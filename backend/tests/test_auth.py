import hashlib

import pytest
from helpers import count, get_board, name

from app import db


def sign_in(client, username="user", password="password"):
    return client.post("/api/login", json={"username": username, "password": password})


def test_correct_credentials_set_a_safe_session_cookie(client):
    response = sign_in(client)
    assert response.status_code == 200
    assert response.json()["name"] == {"en": "Atefe Kalamati", "fa": "عاطفه کلماتی"}
    assert "password" not in response.text
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("tidy_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


@pytest.mark.parametrize(("username", "password"), [("user", "wrong"), ("nobody", "password"), ("", "")])
def test_wrong_credentials_get_one_generic_message(client, username, password):
    response = sign_in(client, username, password)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("username", ["ali", "maryam", "reza"])
def test_team_members_cannot_sign_in(client, conn, username):
    assert count(conn, "users", "username = ? AND password_hash IS NULL", (username,)) == 1
    assert sign_in(client, username, "password").status_code == 401
    assert sign_in(client, username, "").status_code == 401


def test_username_is_case_insensitive(client):
    assert sign_in(client, "USER").status_code == 200


def test_me_needs_a_session(client):
    assert client.get("/api/me").status_code == 401
    sign_in(client)
    body = client.get("/api/me").json()
    assert body["username"] == "user"
    assert body["name"] == {"en": "Atefe Kalamati", "fa": "عاطفه کلماتی"}
    assert body["initials"] == {"en": "AK", "fa": "عک"}


def test_health_stays_public(client):
    assert client.get("/api/health").status_code == 200


def test_logout_ends_the_session(client, conn):
    sign_in(client)
    token = client.cookies["tidy_session"]
    assert client.post("/api/logout").status_code == 204
    assert count(conn, "sessions") == 0
    client.cookies.set("tidy_session", token)
    assert client.get("/api/me").status_code == 401


def test_logout_needs_a_session(client):
    assert client.post("/api/logout").status_code == 401


def test_expired_session_is_rejected_and_purged(client, conn):
    sign_in(client)
    conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00.000Z'")
    assert client.get("/api/me").status_code == 401
    db.purge(conn)
    assert count(conn, "sessions") == 0


def test_sessions_survive_a_server_restart(db_file):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as first:
        sign_in(first)
        cookie = first.cookies["tidy_session"]
    with TestClient(app) as second:  # the session lives in the database, so a new process accepts it
        second.cookies.set("tidy_session", cookie)
        assert second.get("/api/me").status_code == 200


def test_only_hashes_are_stored(client, conn):
    sign_in(client)
    token = client.cookies["tidy_session"]
    stored = conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored
    password_hash = conn.execute("SELECT password_hash FROM users WHERE username = 'user'").fetchone()[0]
    assert "password" not in password_hash and ":" in password_hash


def test_api_answers_are_never_cached(client):
    assert client.get("/api/me").headers["cache-control"] == "no-store"
    assert client.get("/api/health").headers["cache-control"] == "no-store"


def test_first_sign_in_creates_the_sample_board_once(client, conn):
    assert count(conn, "boards") == 0
    sign_in(client)
    assert count(conn, "boards") == 1
    assert count(conn, "cards") == 10
    sign_in(client)  # signing in again must not create or change anything
    assert count(conn, "boards") == 1
    assert count(conn, "cards") == 10
    assert count(conn, "board_members") == 4


def test_many_first_sign_ins_at_once_still_make_one_board(client, conn):
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    from app.main import app

    def one_sign_in(_):
        return TestClient(app).post("/api/login", json={"username": "user", "password": "password"}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(one_sign_in, range(8)))
    assert statuses == [200] * 8
    assert count(conn, "boards") == 1 and count(conn, "cards") == 10 and count(conn, "board_members") == 4


# Every route except login, health and the static files needs a session.
PROTECTED = [
    ("get", "/api/me", None),
    ("post", "/api/logout", None),
    ("get", "/api/board", None),
    ("get", "/api/settings", None),
    ("patch", "/api/settings", {"language": "fa"}),
    ("patch", "/api/columns/todo", {"collapsed": True}),
    ("post", "/api/cards", {"columnId": "todo", "title": "x"}),
    ("patch", "/api/cards/x", {"title": "y"}),
    ("delete", "/api/cards/x", None),
    ("post", "/api/cards/x/restore", None),
    ("post", "/api/cards/x/move", {"columnId": "todo", "index": 0}),
    ("post", "/api/cards/x/members", {"userId": "u"}),
    ("delete", "/api/cards/x/members/u", None),
    ("post", "/api/cards/x/post-progress", None),
    ("post", "/api/spaces/general/messages", {"text": "hi"}),
    ("post", "/api/spaces/general/tasks", {"text": "hi"}),
    ("post", "/api/spaces/general/read", None),
    ("post", "/api/images?fileName=a.png", None),
    ("get", "/api/images/x", None),
]


@pytest.mark.parametrize(("method", "path", "body"), PROTECTED)
def test_every_data_route_needs_sign_in(client, method, path, body):
    response = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert response.status_code == 401


def test_each_user_gets_their_own_board(me, other):
    mine, theirs = get_board(me), get_board(other)
    assert set(mine["cards"]).isdisjoint(theirs["cards"])
    assert mine["currentUserId"] != theirs["currentUserId"]
    assert name(theirs["members"][theirs["currentUserId"]]["name"]) == "Other User"
