import pytest
from helpers import card, column, events, get_board, name, new_card, order


def room(board, title):
    return card(board, title)["id"]


# ---- messages --------------------------------------------------------------------------------------


def test_send_a_message_to_general_and_to_a_room(me):
    board = get_board(me)
    sent = me.post("/api/spaces/general/messages", json={"text": "Hello team"})
    assert sent.status_code == 201
    message = sent.json()
    assert message["type"] == "message" and message["text"] == "Hello team"  # plain string: not translated
    assert message["authorId"] == board["currentUserId"] and message["createdAt"].endswith("Z")
    task_room = room(board, "Task chat room")
    me.post(f"/api/spaces/{task_room}/messages", json={"text": "In the room"})
    after = get_board(me)
    assert after["messages"]["general"][-1]["text"] == "Hello team"
    assert after["messages"][task_room][-1]["text"] == "In the room"
    assert int(after["messages"]["general"][-1]["id"]) > int(after["messages"]["general"][-2]["id"])  # ids only grow


def test_a_message_needs_text_or_an_image_and_a_real_conversation(me):
    assert me.post("/api/spaces/general/messages", json={}).status_code == 422
    assert me.post("/api/spaces/general/messages", json={"text": "   "}).status_code == 422
    assert me.post("/api/spaces/general/messages", json={"text": "x" * 5001}).status_code == 422
    assert me.post("/api/spaces/nope/messages", json={"text": "hi"}).status_code == 404
    assert len(get_board(me)["messages"]["general"]) == 5


def test_other_users_cannot_post_in_my_conversations(me, other):
    mine = room(get_board(me), "Task chat room")
    assert other.post(f"/api/spaces/{mine}/messages", json={"text": "hi"}).status_code == 404
    assert other.post(f"/api/spaces/{mine}/read").status_code == 404
    other.post("/api/spaces/general/messages", json={"text": "my own general"})
    theirs = get_board(other)["messages"]["general"]
    assert theirs[-1]["text"] == "my own general" and len(theirs) == 6  # their own General: the sample five plus this one
    assert len(get_board(me)["messages"]["general"]) == 5


# ---- tasks from messages ---------------------------------------------------------------------------


def test_create_a_task_from_a_message(me):
    board = get_board(me)
    response = me.post("/api/spaces/general/tasks", json={"text": " Buy milk "})
    assert response.status_code == 201
    created, message = response.json()["card"], response.json()["message"]
    assert created["title"] == "Buy milk" and created["priority"] == "medium" and created["details"] == ""
    assert created["memberIds"] == [board["currentUserId"]]  # assigned to its creator
    assert message["type"] == "task" and message["cardId"] == created["id"]
    after = get_board(me)
    assert order(after, "todo")[-1] == "Buy milk"  # new tasks start in To do
    assert after["messages"]["general"][-1]["cardId"] == created["id"]  # announced where it came from
    assert me.post(f"/api/spaces/{created['id']}/messages", json={"text": "room works"}).status_code == 201


def test_a_task_can_come_from_a_card_room_and_must_have_text(me):
    source = room(get_board(me), "Task chat room")
    made = me.post(f"/api/spaces/{source}/tasks", json={"text": "Follow up"}).json()
    assert get_board(me)["messages"][source][-1]["cardId"] == made["card"]["id"]
    assert me.post("/api/spaces/general/tasks", json={"text": ""}).status_code == 422
    assert me.post("/api/spaces/nope/tasks", json={"text": "x"}).status_code == 404


# ---- unread ----------------------------------------------------------------------------------------


def test_marking_a_conversation_read_clears_its_unread_count(me):
    board = get_board(me)
    task_room = room(board, "Task chat room")
    assert board["unread"] == {"general": 2, task_room: 1}
    assert me.post("/api/spaces/general/read").status_code == 204
    assert get_board(me)["unread"] == {task_room: 1}
    assert me.post(f"/api/spaces/{task_room}/read").status_code == 204
    assert get_board(me)["unread"] == {}


def test_my_own_messages_never_count_as_unread(me):
    me.post("/api/spaces/general/read")
    me.post("/api/spaces/general/messages", json={"text": "mine"})
    me.post("/api/spaces/general/tasks", json={"text": "mine too"})
    assert get_board(me)["unread"].get("general") is None


def test_a_message_from_someone_else_is_unread_until_read(me, conn):
    board = get_board(me)
    me.post("/api/spaces/general/read")
    ali = next(i for i, m in board["members"].items() if name(m["name"]).startswith("Ali"))
    space = conn.execute("SELECT id FROM spaces WHERE kind = 'general'").fetchone()[0]
    for text in ("one", "two", "three"):
        conn.execute("INSERT INTO messages (space_id, author_id, kind, text, created_at) VALUES (?, ?, 'message', ?, '2026-11-15T09:00:00.000Z')", (space, ali, text))
    assert get_board(me)["unread"]["general"] == 3
    me.post("/api/spaces/general/read")
    assert "general" not in get_board(me)["unread"]


def test_read_state_is_per_user(me, other):
    me.post("/api/spaces/general/read")
    assert "general" not in get_board(me)["unread"]
    assert get_board(other)["unread"]["general"] == 2  # the other user's own General is untouched


# ---- deleting a card and Undo ----------------------------------------------------------------------


def test_a_deleted_card_and_everything_around_it_disappears_until_undo(me):
    board = get_board(me)
    target = card(board, "Task chat room")  # has a room, an announcement in General and 1 unread message
    assert me.delete(f"/api/cards/{target['id']}").status_code == 204
    after = get_board(me)
    assert target["id"] not in after["cards"]
    assert order(after, "doing") == ["Drag and drop cards", "Jalali date picker"]
    assert target["id"] not in after["messages"] and target["id"] not in after["unread"]  # its room is hidden
    assert all(m["type"] != "task" for m in after["messages"]["general"])  # so is the "task created" announcement
    assert me.post(f"/api/spaces/{target['id']}/messages", json={"text": "hi"}).status_code == 404
    assert me.patch(f"/api/cards/{target['id']}", json={"title": "x"}).status_code == 404
    assert me.delete(f"/api/cards/{target['id']}").status_code == 404  # already deleted


def test_undo_puts_everything_back_exactly(me):
    before = get_board(me)
    target = card(before, "Task chat room")
    me.delete(f"/api/cards/{target['id']}")
    restored = me.post(f"/api/cards/{target['id']}/restore")
    assert restored.status_code == 200 and restored.json() == target
    after = get_board(me)
    assert after == before  # same column order, same room, same announcement, same unread counts, same room-list order


def test_undo_returns_a_card_to_its_exact_place_among_the_others(me):
    before = get_board(me)
    middle = card(before, "Jalali date picker")
    me.delete(f"/api/cards/{middle['id']}")
    new_card(me, "Added meanwhile", "doing")
    me.post(f"/api/cards/{middle['id']}/restore")
    assert order(get_board(me), "doing") == ["Drag and drop cards", "Jalali date picker", "Task chat room", "Added meanwhile"]


def test_restoring_a_card_that_is_not_deleted_is_not_found(me):
    assert me.post(f"/api/cards/{card(get_board(me), 'Task chat room')['id']}/restore").status_code == 404


def test_a_deleted_cards_labels_and_assignees_come_back_with_it(me):
    target = card(get_board(me), "Task chat room")
    me.delete(f"/api/cards/{target['id']}")
    back = me.post(f"/api/cards/{target['id']}/restore").json()
    assert back["labelIds"] == ["design", "frontend"] and back["memberIds"] == target["memberIds"]


def test_deleting_a_column_worth_of_cards_leaves_the_column(me):
    board = get_board(me)
    for title in list(order(board, "done")):
        me.delete(f"/api/cards/{card(board, title)['id']}")
    after = get_board(me)
    assert column(after, "done")["cardIds"] == [] and column(after, "done")["id"] == "done"
    assert len(after["cards"]) == 8


@pytest.mark.parametrize("other_route", ["restore", "move"])
def test_other_users_cannot_undo_or_move_my_cards(me, other, other_route):
    target = card(get_board(me), "Task chat room")["id"]
    me.delete(f"/api/cards/{target}")
    body = {"json": {"columnId": "todo", "index": 0}} if other_route == "move" else {}
    assert other.post(f"/api/cards/{target}/{other_route}", **body).status_code == 404
    assert me.post(f"/api/cards/{target}/restore").status_code == 200


def test_the_rooms_list_order_is_creation_order(me):
    newest = new_card(me, "Newest")
    board = get_board(me)
    assert list(board["cards"])[-1] == newest["id"] and len(board["cards"]) == 11
    assert events(board, newest["id"]) == []  # a brand new card has an empty room
