import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app


@pytest.fixture
def client():
    auth.SESSIONS.clear()
    return TestClient(app)


def sign_in(client, username="user", password="password"):
    return client.post("/api/login", json={"username": username, "password": password})


def test_correct_credentials_set_a_safe_session_cookie(client):
    response = sign_in(client)
    assert response.status_code == 200
    assert response.json()["name"] == {"en": "Atefe Kalamati", "fa": "عاطفه کلماتی"}
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
def test_team_members_cannot_sign_in(client, username):
    assert username in auth.USERS
    assert sign_in(client, username, "password").status_code == 401


def test_me_needs_a_session(client):
    assert client.get("/api/me").status_code == 401
    sign_in(client)
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json() == {
        "username": "user",
        "name": {"en": "Atefe Kalamati", "fa": "عاطفه کلماتی"},
        "initials": {"en": "AK", "fa": "عک"},
    }


def test_health_stays_public(client):
    assert client.get("/api/health").status_code == 200


def test_logout_ends_the_session(client):
    sign_in(client)
    token = client.cookies["tidy_session"]
    assert client.post("/api/logout").status_code == 204
    assert token not in auth.SESSIONS
    client.cookies.set("tidy_session", token)
    assert client.get("/api/me").status_code == 401


def test_logout_needs_a_session(client):
    assert client.post("/api/logout").status_code == 401


def test_expired_session_is_rejected_and_removed(client):
    sign_in(client)
    token = client.cookies["tidy_session"]
    auth.SESSIONS[token] = ("user", time.time() - 1)
    assert client.get("/api/me").status_code == 401
    assert token not in auth.SESSIONS


def test_password_is_stored_as_a_hash():
    stored = auth.USERS["user"]["password_hash"]
    assert "password" not in stored
    assert auth.verify_password("password", stored)
    assert not auth.verify_password("Password", stored)


def test_api_answers_are_never_cached(client):
    assert client.get("/api/me").headers["cache-control"] == "no-store"
    assert client.get("/api/health").headers["cache-control"] == "no-store"
