import pytest
from helpers import card, column, count, events, get_board, member, name, new_card, order


def test_the_board_has_the_shape_of_the_frontend_state(me):
    board = get_board(me)
    assert set(board) == {"currentUserId", "language", "density", "columns", "cards", "labels", "members", "messages", "unread"}
    assert [c["id"] for c in board["columns"]] == ["ideas", "todo", "doing", "review", "done"]
    assert [(c["id"], c["wipLimit"]) for c in board["columns"] if c["wipLimit"]] == [("doing", 3), ("review", 2)]
    assert all(c["name"] is None and c["collapsed"] is False for c in board["columns"])
    assert len(board["cards"]) == 10
    assert [label["id"] for label in board["labels"]] == ["design", "frontend", "bug", "docs", "testing"]
    # The signed-in user first, then the teammates, in the original order.
    assert [name(m["name"]) for m in board["members"].values()] == ["Atefe Kalamati", "Ali Rezaei", "Maryam Karimi", "Reza Mohammadi"]
    assert board["currentUserId"] == next(iter(board["members"]))
    assert (board["language"], board["density"]) == ("en", "comfortable")


def test_sample_text_has_both_languages_and_cards_keep_their_order(me):
    board = get_board(me)
    drag = card(board, "Drag and drop cards")
    assert drag["title"] == {"en": "Drag and drop cards", "fa": "کشیدن و رها کردن کارت‌ها"}
    assert drag["priority"] == "high" and drag["progress"] == 60
    assert drag["labelIds"] == ["frontend"]
    assert [name(board["members"][m]["name"]) for m in drag["memberIds"]] == ["Ali Rezaei", "Atefe Kalamati"]  # the order they were added
    assert order(board, "doing") == ["Drag and drop cards", "Jalali date picker", "Task chat room"]
    assert list(board["cards"])[:3] == [card(board, t)["id"] for t in ("Board progress bar", "Keyboard shortcut sheet", "Empty column state")]  # creation order
    assert card(board, "Board progress bar")["dueDate"] is None
    assert card(board, "Drag and drop cards")["dueDate"] is not None


def test_sample_messages_unread_and_images(me):
    board = get_board(me)
    general = board["messages"]["general"]
    assert [m["type"] for m in general] == ["message", "task", "message", "message", "message"]
    assert general[2]["image"] == {"file": "empty-states-moodboard.png"}  # a placeholder: no bytes, so no src
    assert general[2]["text"]["fa"] == "مودبورد حالت‌های خالی ستون"
    assert general[1]["cardId"] == card(board, "Task chat room")["id"]
    room = board["messages"][card(board, "Task chat room")["id"]]
    assert [m.get("event") for m in room if m["type"] == "event"] == ["added", "added", "progress"]
    assert next(m for m in room if m.get("event") == "progress")["value"] == 45
    assert board["unread"] == {"general": 2, card(board, "Task chat room")["id"]: 1}
    assert all(m["createdAt"].endswith("Z") for msgs in board["messages"].values() for m in msgs)


# ---- settings --------------------------------------------------------------------------------------


def test_settings_are_stored_for_the_user(me):
    assert me.get("/api/settings").json() == {"language": "en", "density": "comfortable"}
    assert me.patch("/api/settings", json={"language": "fa"}).json() == {"language": "fa", "density": "comfortable"}
    assert me.patch("/api/settings", json={"density": "compact"}).json() == {"language": "fa", "density": "compact"}
    board = get_board(me)
    assert (board["language"], board["density"]) == ("fa", "compact")


@pytest.mark.parametrize("body", [{"language": "de"}, {"density": "tiny"}, {"language": None}])
def test_invalid_settings_are_rejected(me, body):
    assert me.patch("/api/settings", json=body).status_code == 422
    assert me.get("/api/settings").json() == {"language": "en", "density": "comfortable"}


def test_settings_belong_to_each_user(me, other):
    me.patch("/api/settings", json={"language": "fa"})
    assert other.get("/api/settings").json()["language"] == "en"


# ---- columns ---------------------------------------------------------------------------------------


def test_rename_wip_and_collapse_a_column(me):
    changed = me.patch("/api/columns/todo", json={"name": "  Next up ", "wipLimit": 4, "collapsed": True}).json()["columns"]
    todo = next(c for c in changed if c["id"] == "todo")
    assert (todo["name"], todo["wipLimit"], todo["collapsed"]) == ("Next up", 4, True)
    assert len(todo["cardIds"]) == 2
    board = get_board(me)
    assert column(board, "todo")["name"] == "Next up"
    # An empty name goes back to the translated default; a null limit removes the limit.
    me.patch("/api/columns/todo", json={"name": ""})
    me.patch("/api/columns/todo", json={"wipLimit": None, "collapsed": False})
    todo = column(get_board(me), "todo")
    assert (todo["name"], todo["wipLimit"], todo["collapsed"]) == (None, None, False)


def test_a_partial_column_change_leaves_the_rest(me):
    me.patch("/api/columns/doing", json={"collapsed": True})
    doing = column(get_board(me), "doing")
    assert doing["wipLimit"] == 3 and doing["collapsed"] is True


@pytest.mark.parametrize("body", [{"wipLimit": 0}, {"wipLimit": -1}, {"collapsed": None}, {"name": "x" * 101}])
def test_invalid_column_changes_are_rejected(me, body):
    assert me.patch("/api/columns/todo", json=body).status_code == 422


def test_an_unknown_column_is_not_found(me):
    assert me.patch("/api/columns/nope", json={"collapsed": True}).status_code == 404


# ---- creating and editing cards --------------------------------------------------------------------


def test_create_a_card_at_the_end_of_its_column_with_a_room(me):
    board = get_board(me)
    ali, maryam = member(board, "Ali"), member(board, "Maryam")
    created = new_card(me, "Write docs", "review", details="Part 6", priority="high", dueDate="2026-12-01", labelIds=["docs", "bug"], memberIds=[maryam, ali])
    assert created["title"] == "Write docs"  # user text is a plain string: it is not translated
    assert created["details"] == "Part 6" and created["priority"] == "high" and created["dueDate"] == "2026-12-01"
    assert created["labelIds"] == ["docs", "bug"] and created["memberIds"] == [maryam, ali]  # order is kept
    assert created["progress"] == 0
    board = get_board(me)
    assert order(board, "review")[-1] == "Write docs"
    assert list(board["cards"])[-1] == created["id"]  # the newest room is last
    assert me.post(f"/api/spaces/{created['id']}/messages", json={"text": "first!"}).status_code == 201  # it has a room


def test_a_card_needs_a_title_and_valid_references(me):
    ok = {"columnId": "todo", "title": "x"}
    assert me.post("/api/cards", json={**ok, "title": ""}).status_code == 422
    assert me.post("/api/cards", json={**ok, "title": "   "}).status_code == 422
    assert me.post("/api/cards", json={**ok, "priority": "urgent"}).status_code == 422
    assert me.post("/api/cards", json={**ok, "dueDate": "2026-13-45"}).status_code == 422
    assert me.post("/api/cards", json={**ok, "labelIds": ["nope"]}).status_code == 422
    assert me.post("/api/cards", json={**ok, "memberIds": ["not-a-member"]}).status_code == 422
    assert me.post("/api/cards", json={**ok, "columnId": "nope"}).status_code == 404
    assert me.post("/api/cards", json={"title": "x"}).status_code == 422
    assert len(get_board(me)["cards"]) == 10  # nothing was half-created


def test_the_client_may_choose_the_card_id(me):
    chosen = "5f0b7c1e-6a3d-4c52-9a55-0d3f7a1c9b11"
    assert new_card(me, "Mine", id=chosen)["id"] == chosen
    assert me.post("/api/cards", json={"id": chosen, "columnId": "todo", "title": "again"}).status_code == 409
    assert me.post("/api/cards", json={"id": "not-a-uuid", "columnId": "todo", "title": "bad"}).status_code == 422


def test_editing_changes_only_what_is_sent(me):
    board = get_board(me)
    target = card(board, "Drag and drop cards")
    edited = me.patch(f"/api/cards/{target['id']}", json={"priority": "low", "progress": 75}).json()
    assert (edited["priority"], edited["progress"]) == ("low", 75)
    assert edited["title"] == target["title"] and edited["labelIds"] == target["labelIds"] and edited["memberIds"] == target["memberIds"]


def test_editing_a_sample_text_replaces_both_languages(me):
    target = card(get_board(me), "Drag and drop cards")
    edited = me.patch(f"/api/cards/{target['id']}", json={"title": " My title ", "details": "Mine"}).json()
    assert edited["title"] == "My title" and edited["details"] == "Mine"  # plain strings now, no Persian left over


def test_labels_members_and_due_date_can_be_replaced_or_cleared(me):
    board = get_board(me)
    target = card(board, "Task chat room")
    ali = member(board, "Ali")
    edited = me.patch(f"/api/cards/{target['id']}", json={"labelIds": ["bug"], "memberIds": [ali], "dueDate": None}).json()
    assert edited["labelIds"] == ["bug"] and edited["memberIds"] == [ali] and edited["dueDate"] is None
    edited = me.patch(f"/api/cards/{target['id']}", json={"dueDate": "2027-01-02"}).json()
    assert edited["dueDate"] == "2027-01-02"
    assert me.patch(f"/api/cards/{target['id']}", json={"memberIds": []}).json()["memberIds"] == []
    # Changing assignees through an edit writes no room events (that is what the assignee routes are for).
    assert [e["event"] for e in events(get_board(me), target["id"])] == ["added", "added", "progress"]


@pytest.mark.parametrize(
    "body",
    [{"title": ""}, {"title": None}, {"priority": "urgent"}, {"progress": 101}, {"progress": -1}, {"dueDate": "yesterday"}, {"labelIds": ["nope"]}, {"memberIds": ["nobody"]}, {"progress": None}],
)
def test_invalid_edits_are_rejected_and_change_nothing(me, body):
    target = card(get_board(me), "Drag and drop cards")
    assert me.patch(f"/api/cards/{target['id']}", json=body).status_code == 422
    assert card(get_board(me), "Drag and drop cards") == target


def test_unknown_cards_are_not_found(me):
    assert me.patch("/api/cards/nope", json={"title": "x"}).status_code == 404
    assert me.delete("/api/cards/nope").status_code == 404
    assert me.post("/api/cards/nope/restore").status_code == 404
    assert me.post("/api/cards/nope/move", json={"columnId": "todo", "index": 0}).status_code == 404
    assert me.post("/api/cards/nope/post-progress").status_code == 404


# ---- assignees and progress events -----------------------------------------------------------------


def test_adding_and_removing_an_assignee_writes_room_events(me):
    board = get_board(me)
    target = card(board, "Keyboard shortcut sheet")  # nobody assigned
    ali = member(board, "Ali")
    added = me.post(f"/api/cards/{target['id']}/members", json={"userId": ali})
    assert added.status_code == 201 and added.json()["memberIds"] == [ali]
    removed = me.delete(f"/api/cards/{target['id']}/members/{ali}")
    assert removed.status_code == 200 and removed.json()["memberIds"] == []
    room = events(get_board(me), target["id"])
    assert [(e["event"], e["memberId"], e["authorId"], e["byAi"]) for e in room] == [("added", ali, board["currentUserId"], False), ("removed", ali, board["currentUserId"], False)]


def test_assignee_errors(me):
    board = get_board(me)
    target = card(board, "Drag and drop cards")  # Ali and the user are on it
    ali = member(board, "Ali")
    assert me.post(f"/api/cards/{target['id']}/members", json={"userId": ali}).status_code == 409
    assert me.post(f"/api/cards/{target['id']}/members", json={"userId": "nobody"}).status_code == 422
    assert me.delete(f"/api/cards/{target['id']}/members/{member(board, 'Reza')}").status_code == 404
    assert me.post("/api/cards/nope/members", json={"userId": ali}).status_code == 404


def test_posting_progress_writes_the_current_value(me):
    board = get_board(me)
    target = card(board, "Jalali date picker")  # in progress, 35%
    assert me.post(f"/api/cards/{target['id']}/post-progress").status_code == 204
    done = card(board, "Set up Next.js project")  # in Done: always 100
    me.patch(f"/api/cards/{done['id']}", json={"progress": 40})
    me.post(f"/api/cards/{done['id']}/post-progress")
    board = get_board(me)
    assert [e["value"] for e in events(board, target["id"])] == [35]
    assert [e["value"] for e in events(board, done["id"])] == [100]


def test_each_user_only_sees_their_own_cards(me, other):
    mine = card(get_board(me), "Drag and drop cards")
    assert other.patch(f"/api/cards/{mine['id']}", json={"title": "hacked"}).status_code == 404
    assert other.delete(f"/api/cards/{mine['id']}").status_code == 404
    assert other.post(f"/api/cards/{mine['id']}/move", json={"columnId": "todo", "index": 0}).status_code == 404
    assert other.post(f"/api/spaces/{mine['id']}/messages", json={"text": "hi"}).status_code == 404
    assert card(get_board(me), "Drag and drop cards")["title"] == mine["title"]


def test_nothing_is_left_behind_by_a_rejected_card(me, conn):
    before = {t: count(conn, t) for t in ("cards", "spaces", "card_labels", "card_members")}
    me.post("/api/cards", json={"columnId": "todo", "title": "x", "labelIds": ["design", "nope"]})
    assert {t: count(conn, t) for t in before} == before  # the transaction rolled back
