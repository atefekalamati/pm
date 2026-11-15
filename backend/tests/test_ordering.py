"""Card order: gapped integer positions (docs/DATABASE.md section 3)."""

from fastapi.testclient import TestClient
from helpers import card, events, get_board, new_card, order, positions

from app import board as board_service
from app.main import app


def move(client, board, title, column, index):
    response = client.post(f"/api/cards/{card(board, title)['id']}/move", json={"columnId": column, "index": index})
    assert response.status_code == 200, response.text
    return response.json()["columns"]


def test_sample_cards_start_with_gaps_of_1024(me, conn):
    assert positions(conn, "doing") == [("Drag and drop cards", 1024), ("Jalali date picker", 2048), ("Task chat room", 3072)]


def test_a_new_card_goes_to_the_end_of_its_column(me, conn):
    new_card(me, "Last", "doing")
    assert positions(conn, "doing")[-1] == ("Last", 4096)
    new_card(me, "First ever", "done")  # done has 1024 and 2048
    assert positions(conn, "done")[-1] == ("First ever", 3072)


def test_moving_inside_a_column_changes_one_card(me, conn):
    board = get_board(me)
    columns = move(me, board, "Task chat room", "doing", 0)
    assert [c["cardIds"] for c in columns if c["id"] == "doing"][0][0] == card(board, "Task chat room")["id"]
    assert order(get_board(me), "doing") == ["Task chat room", "Drag and drop cards", "Jalali date picker"]
    assert positions(conn, "doing")[0] == ("Task chat room", 512)  # halfway between the top (0) and the first card
    assert [p for _, p in positions(conn, "doing")][1:] == [1024, 2048]  # the others were not touched
    assert events(get_board(me), card(board, "Task chat room")["id"])[-1]["event"] != "moved"  # same column: no event


def test_moving_between_two_cards_takes_the_middle(me, conn):
    board = get_board(me)
    move(me, board, "Task chat room", "doing", 1)
    assert positions(conn, "doing") == [("Drag and drop cards", 1024), ("Task chat room", 1536), ("Jalali date picker", 2048)]


def test_moving_to_the_end_appends_with_a_full_gap(me, conn):
    move(me, get_board(me), "Drag and drop cards", "doing", 99)  # an index past the end is clamped
    assert positions(conn, "doing")[-1] == ("Drag and drop cards", 4096)
    assert order(get_board(me), "doing") == ["Jalali date picker", "Task chat room", "Drag and drop cards"]


def test_moving_to_another_column_logs_one_moved_event(me, conn):
    board = get_board(me)
    columns = move(me, board, "Empty column state", "review", 0)
    assert [c["cardIds"] for c in columns if c["id"] == "todo"][0] == [card(board, "Column unit tests")["id"]]
    board = get_board(me)
    assert order(board, "review") == ["Empty column state", "Fix mixed text direction"]
    moved = [e for e in events(board, card(board, "Empty column state")["id"]) if e["event"] == "moved"]
    assert len(moved) == 1 and moved[0]["columnId"] == "review" and moved[0]["authorId"] == board["currentUserId"]
    assert moved[0]["byAi"] is False


def test_one_move_is_one_write_inside_a_column_and_two_across(me, monkeypatch):
    seen = []
    original = board_service.move_card

    def count_writes(conn_, *args, **kwargs):  # measured on the server's own connection
        start = conn_.total_changes
        try:
            return original(conn_, *args, **kwargs)
        finally:
            seen.append(conn_.total_changes - start)

    monkeypatch.setattr(board_service, "move_card", count_writes)
    board = get_board(me)
    move(me, board, "Jalali date picker", "doing", 0)  # inside a column
    move(me, board, "Jalali date picker", "done", 0)  # to another column
    assert seen == [1, 2]  # UPDATE cards  |  UPDATE cards + the "moved" event row


def test_putting_a_card_where_it_already_is_changes_nothing(me, conn):
    board = get_board(me)
    before = positions(conn, "doing")
    move(me, board, "Jalali date picker", "doing", 1)
    assert positions(conn, "doing") == before
    assert not [e for e in events(get_board(me), card(board, "Jalali date picker")["id"]) if e["event"] == "moved"]


def test_a_deleted_card_does_not_count_as_a_neighbour(me, conn):
    board = get_board(me)
    me.delete(f"/api/cards/{card(board, 'Jalali date picker')['id']}")
    move(me, board, "Task chat room", "doing", 1)  # only one other live card is left; the deleted one is ignored
    assert order(get_board(me), "doing") == ["Drag and drop cards", "Task chat room"]


def test_invalid_moves(me):
    board = get_board(me)
    target = card(board, "Task chat room")["id"]
    assert me.post(f"/api/cards/{target}/move", json={"columnId": "nope", "index": 0}).status_code == 404
    assert me.post(f"/api/cards/{target}/move", json={"columnId": "doing", "index": -1}).status_code == 422
    assert me.post(f"/api/cards/{target}/move", json={"columnId": "doing"}).status_code == 422
    assert order(get_board(me), "doing") == order(board, "doing")


# ---- when the gaps run out -------------------------------------------------------------------------


def squeeze(me, count_):
    """Puts new cards one after another between the first two cards of To do, halving the gap each time."""
    names = [f"N{i}" for i in range(1, count_ + 1)]
    for title in names:
        new_card(me, title, "todo")
    return names


def test_gaps_that_run_out_renumber_the_whole_column_in_one_transaction(me, conn, monkeypatch):
    calls = []
    original = board_service.renumber_column

    def spy(conn_, column_id, exclude_card_id=None):
        calls.append(conn_.in_transaction)  # called from inside the move's transaction
        before = conn_.total_changes
        original(conn_, column_id, exclude_card_id)
        calls.append(conn_.total_changes - before)  # one statement, one row per card

    monkeypatch.setattr(board_service, "renumber_column", spy)
    names = squeeze(me, 12)  # To do: Empty column state (1024), Column unit tests (2048), N1 ... N12 after them
    expected = ["Empty column state", "Column unit tests"] + names

    for i, title in enumerate(names, start=1):
        board = get_board(me)
        move(me, board, title, "todo", 1)  # always right below the top card: each insert halves the same gap
        expected.remove(title)
        expected.insert(1, title)
        assert order(get_board(me), "todo") == expected, f"after moving {title}"
        if i <= 10:
            assert calls == []  # 1024 -> 512 -> ... -> 1: about ten halvings fit
        if i == 11:  # the gap between 1024 and 1025 is gone: this move renumbers the column first
            assert calls[0] is True
            assert calls[1] == 12 + 1  # every other card of the column (13 of 14) got a new position
            rest = [p for t, p in positions(conn, "todo") if t != title]
            assert rest == [1024 * n for n in range(1, len(rest) + 1)]  # evenly respaced again, order kept
    assert len(calls) == 2  # the 12th move found room again and did not renumber


def test_a_failed_renumbering_leaves_every_position_unchanged(me, conn, monkeypatch):
    names = squeeze(me, 12)
    for title in names[:10]:
        move(me, get_board(me), title, "todo", 1)  # use up the gap (11th move would renumber)
    snapshot = positions(conn, "todo")
    order_before = order(get_board(me), "todo")

    original = board_service.renumber_column

    def renumber_then_fail(conn_, column_id, exclude_card_id=None):
        original(conn_, column_id, exclude_card_id)  # the positions really are rewritten...
        raise RuntimeError("boom")  # ...and then the request fails

    monkeypatch.setattr(board_service, "renumber_column", renumber_then_fail)
    quiet = TestClient(app, raise_server_exceptions=False)
    quiet.cookies.update(me.cookies)
    response = quiet.post(f"/api/cards/{card(get_board(me), names[10])['id']}/move", json={"columnId": "todo", "index": 1})
    assert response.status_code == 500
    assert positions(conn, "todo") == snapshot  # rolled back together with the move
    assert order(get_board(me), "todo") == order_before
    # Nothing is left locked or half-done: the same move works once the fault is gone.
    monkeypatch.setattr(board_service, "renumber_column", original)
    assert quiet.post(f"/api/cards/{card(get_board(me), names[10])['id']}/move", json={"columnId": "todo", "index": 1}).status_code == 200
    assert order(get_board(me), "todo")[1] == names[10]


def test_renumbering_keeps_deleted_cards_in_their_place_for_undo(me, conn):
    board = get_board(me)
    gone = card(board, "Jalali date picker")  # the middle card of In progress
    me.delete(f"/api/cards/{gone['id']}")
    column_id = conn.execute("SELECT id FROM columns WHERE slug = 'doing'").fetchone()[0]
    conn.execute("UPDATE cards SET position = 5 WHERE title = 'Drag and drop cards'")  # cramped positions
    conn.execute("UPDATE cards SET position = 6 WHERE title = 'Jalali date picker'")
    conn.execute("UPDATE cards SET position = 7 WHERE title = 'Task chat room'")
    board_service.renumber_column(conn, column_id)
    rows = [(r["title"], r["position"]) for r in conn.execute("SELECT title, position FROM cards WHERE column_id = ? ORDER BY position", (column_id,))]
    assert rows == [("Drag and drop cards", 1024), ("Jalali date picker", 2048), ("Task chat room", 3072)]  # all three, same order
    me.post(f"/api/cards/{gone['id']}/restore")
    assert order(get_board(me), "doing") == ["Drag and drop cards", "Jalali date picker", "Task chat room"]


def test_equal_positions_are_ordered_by_creation_and_never_break_a_move(me, conn):
    conn.execute("UPDATE cards SET position = 1024 WHERE title IN ('Drag and drop cards', 'Jalali date picker', 'Task chat room')")
    assert order(get_board(me), "doing") == ["Drag and drop cards", "Jalali date picker", "Task chat room"]  # ties: creation order
    move(me, get_board(me), "Task chat room", "doing", 1)  # no whole number fits between equal neighbours: renumbers first
    assert order(get_board(me), "doing") == ["Drag and drop cards", "Task chat room", "Jalali date picker"]
