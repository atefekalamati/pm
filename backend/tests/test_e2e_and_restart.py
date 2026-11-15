"""The test-only user endpoint, and: every kind of change survives a server restart."""

from fastapi.testclient import TestClient
from helpers import card, get_board, member, name, order, upload

from app.main import app


def test_the_test_only_endpoint_is_absent_unless_enabled(me, monkeypatch):
    # Not registered in a normal run: the route does not exist (the static files answer instead).
    assert not [path for path in me.get("/openapi.json").json()["paths"] if "e2e" in path]
    assert me.post("/api/e2e/users", json={"username": "x"}).status_code == 404


def test_the_test_only_endpoint_makes_a_user_with_a_dated_board(db_file, monkeypatch):
    monkeypatch.setenv("TIDY_E2E", "1")
    import importlib

    from app import main

    fresh = importlib.reload(main)  # routes are registered when the module loads
    try:
        with TestClient(fresh.app) as c:
            made = c.post("/api/e2e/users", json={"username": "e2e-one", "today": "2026-11-08"})
            assert made.status_code == 201 and made.json() == {"username": "e2e-one", "password": "password"}
            assert c.post("/api/e2e/users", json={"username": "e2e-one"}).status_code == 409
            assert c.post("/api/login", json={"username": "e2e-one", "password": "password"}).status_code == 200
            board = get_board(c)
            assert card(board, "Jalali date picker")["dueDate"] == "2026-11-06"  # "today" is the given date, two days ago
            assert name(board["members"][board["currentUserId"]]["name"]) == "Atefe Kalamati"
    finally:
        monkeypatch.delenv("TIDY_E2E")
        importlib.reload(main)


def restart(db_file, cookie):
    """A new server process on the same database file, with the browser's cookie."""
    with TestClient(app) as again:
        again.cookies.set("tidy_session", cookie)
        return get_board(again)


def test_every_kind_of_change_survives_a_server_restart(me, db_file):
    board = get_board(me)
    ali, maryam = member(board, "Ali"), member(board, "Maryam")
    drag = card(board, "Drag and drop cards")["id"]
    room = card(board, "Task chat room")["id"]

    me.patch("/api/settings", json={"language": "fa", "density": "compact"})  # language and density
    created = me.post("/api/cards", json={"columnId": "review", "title": "New one", "labelIds": ["bug"], "memberIds": [ali]}).json()  # new card
    me.patch(f"/api/cards/{drag}", json={"title": "Edited", "priority": "low", "dueDate": "2027-02-03", "progress": 70})  # edit, progress
    me.post(f"/api/cards/{room}/move", json={"columnId": "review", "index": 0})  # move across columns
    me.patch("/api/columns/todo", json={"name": "Next up", "wipLimit": 5, "collapsed": True})  # column name, WIP, collapse
    me.post(f"/api/cards/{drag}/members", json={"userId": maryam})  # assignee
    me.post(f"/api/cards/{drag}/post-progress")  # progress event
    sent = me.post("/api/spaces/general/messages", json={"text": "Hello"}).json()  # message
    image = upload(me, b"\x89PNG-bytes")  # image
    me.post(f"/api/spaces/{room}/messages", json={"text": "pic", "imageId": image["id"]})
    task = me.post("/api/spaces/general/tasks", json={"text": "From a message"}).json()  # task from a message
    me.post("/api/spaces/general/read")  # unread
    expected = get_board(me)

    after = restart(db_file, me.cookies["tidy_session"])
    assert after == expected
    assert (after["language"], after["density"]) == ("fa", "compact")
    assert order(after, "review")[:2] == ["Task chat room", "Fix mixed text direction"] and "New one" in order(after, "review")
    assert [c for c in after["columns"] if c["id"] == "todo"][0] | {"cardIds": None} == {"id": "todo", "name": "Next up", "cardIds": None, "wipLimit": 5, "collapsed": True}
    assert after["cards"][drag]["title"] == "Edited" and after["cards"][drag]["progress"] == 70
    assert maryam in after["cards"][drag]["memberIds"]
    assert after["messages"]["general"][-2]["text"] == "Hello" and after["messages"]["general"][-1]["cardId"] == task["card"]["id"]
    assert after["messages"][room][-1]["image"]["src"] == image["src"]
    assert "general" not in after["unread"]
    assert created["id"] in after["cards"] and sent["id"]


def test_a_deleted_card_and_its_undo_survive_a_restart(me, db_file):
    board = get_board(me)
    gone, back = card(board, "Jalali date picker")["id"], card(board, "Task chat room")["id"]
    me.delete(f"/api/cards/{gone}")
    me.delete(f"/api/cards/{back}")
    me.post(f"/api/cards/{back}/restore")
    after = restart(db_file, me.cookies["tidy_session"])
    assert gone not in after["cards"] and back in after["cards"]
    assert after == get_board(me)
