"""The assistant. The model is always a mock: its answer is whatever the test says it is."""

import json
from datetime import date

import openai
import pytest
from fastapi.testclient import TestClient
from helpers import card, column, count, events, get_board, member, name, order

from app import ai, assistant
from app import board as board_service
from app.main import app
from test_ai import REQUEST, FakeClient, status_error


def answer(reply="Done.", actions=None) -> str:
    return json.dumps({"reply": reply, "actions": actions if actions is not None else []}, ensure_ascii=False)


class Model:
    """Replaces ai.complete: returns the next prepared answer and remembers what it was sent."""

    def __init__(self, monkeypatch, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []
        monkeypatch.setattr(ai, "complete", self)

    def __call__(self, messages, response_format=None):
        self.calls.append({"messages": messages, "response_format": response_format})
        result = self.answers[min(len(self.calls), len(self.answers)) - 1]
        if isinstance(result, Exception):
            raise result
        return result


def ask(client, message="Please help"):
    return client.post("/api/ai/chat", json={"message": message})


def snapshot(client):
    """Everything that must stay the same when nothing is allowed to change."""
    return json.dumps(get_board(client), sort_keys=True), json.dumps(client.get("/api/ai/history").json(), sort_keys=True)


# ---- what the model is sent ------------------------------------------------------------------------


def test_the_prompt_has_the_rules_the_board_the_history_and_the_question(me, monkeypatch):
    monkeypatch.setattr(assistant, "today", lambda: date(2026, 11, 20))
    model = Model(monkeypatch, answer("First."), answer("Second."))
    ask(me, "Hello there")
    ask(me, "And now?")
    first, second = model.calls
    system = first["messages"][0]
    assert system["role"] == "system"
    assert "Today is 2026-11-20" in system["content"]
    assert "language of the user's LATEST message" in system["content"]  # answer in the user's language
    assert "ideas, todo, doing, review, done" in system["content"]
    board = get_board(me)
    for title in ("Drag and drop cards", "Task chat room"):
        assert title in system["content"]
    assert card(board, "Task chat room")["id"] in system["content"] and member(board, "Ali") in system["content"]
    assert first["messages"][1:] == [{"role": "user", "content": "Hello there"}]
    assert second["messages"][1:] == [
        {"role": "user", "content": "Hello there"},
        {"role": "assistant", "content": "First."},
        {"role": "user", "content": "And now?"},
    ]
    assert first["response_format"] == {"type": "json_object"}


def test_the_board_in_the_prompt_has_no_chat_messages_or_images(me, monkeypatch):
    me.post("/api/spaces/general/messages", json={"text": "a secret chat line"})
    model = Model(monkeypatch, answer())
    ask(me)
    prompt = model.calls[0]["messages"][0]["content"]
    assert "a secret chat line" not in prompt and "Morning team" not in prompt
    snapshot_json = json.loads(prompt.split("Current board (JSON):\n", 1)[1])
    assert set(snapshot_json) == {"columns", "cards", "labels", "members"}
    assert "image" not in prompt.lower() or "moodboard" not in prompt  # no image names either


def test_a_persian_message_goes_through_unchanged_and_gets_a_persian_system_instruction_to_follow(me, monkeypatch):
    model = Model(monkeypatch, answer("بله."))
    ask(me, "یک کارت جدید بساز")
    assert model.calls[0]["messages"][-1] == {"role": "user", "content": "یک کارت جدید بساز"}
    assert "Persian or English" in model.calls[0]["messages"][0]["content"]


@pytest.mark.parametrize(("text", "language"), [("Make a card", "en"), ("یک کارت بساز", "fa"), ("Make a card برای تست", "fa"), ("123 !!!", "en")])
def test_language_of_the_user_text(text, language):
    assert assistant.language_of(text) == language


def test_only_the_last_messages_are_sent(me, monkeypatch, conn):
    board_id = conn.execute("SELECT id FROM boards").fetchone()[0]
    user_id = conn.execute("SELECT id FROM users WHERE username = 'user'").fetchone()[0]
    for i in range(30):
        conn.execute(
            "INSERT INTO ai_messages (board_id, user_id, role, content, created_at) VALUES (?, ?, ?, ?, '2026-11-15T08:00:00.000Z')",
            (board_id, user_id, "user" if i % 2 == 0 else "assistant", f"old {i}"),
        )
    model = Model(monkeypatch, answer())
    ask(me, "newest question")
    sent = model.calls[0]["messages"]
    assert assistant.HISTORY_LIMIT == 20
    assert len(sent) == 1 + 20 + 1  # the rules and board, the last 20, the question
    assert [m["content"] for m in sent[1:-1]] == [f"old {i}" for i in range(10, 30)]  # the newest 20, oldest first
    assert sent[-1]["content"] == "newest question"
    assert count(conn, "ai_messages") == 32  # everything is kept; only what is sent is limited


def test_history_is_per_user_and_board(me, other, monkeypatch):
    Model(monkeypatch, answer("mine"))
    ask(me, "my question")
    model = Model(monkeypatch, answer("theirs"))
    ask(other, "their question")
    assert [m["content"] for m in model.calls[0]["messages"][1:]] == ["their question"]  # nothing of mine


# ---- the reply and the history ---------------------------------------------------------------------


def test_a_reply_without_actions_does_not_touch_the_board(me, monkeypatch):
    Model(monkeypatch, answer("Everything is on track.", []))
    before = json.dumps(get_board(me), sort_keys=True)
    response = ask(me, "How is it going?")
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Everything is on track." and body["applied"] == [] and body["problem"] is None
    assert json.dumps(body["board"], sort_keys=True) == before == json.dumps(get_board(me), sort_keys=True)


def test_actions_may_be_null_or_missing(me, monkeypatch):
    Model(monkeypatch, json.dumps({"reply": "ok", "actions": None}), json.dumps({"reply": "ok"}))
    assert ask(me).json()["applied"] == [] and ask(me).json()["applied"] == []


def test_both_sides_of_the_conversation_are_stored(me, monkeypatch):
    Model(monkeypatch, answer("Hi back."))
    ask(me, "Hi")
    history = me.get("/api/ai/history").json()
    assert [(m["role"], m["content"]) for m in history] == [("user", "Hi"), ("assistant", "Hi back.")]
    assert history[1]["changes"] == {"applied": [], "problem": None}
    assert history[0]["changes"] is None and history[0]["createdAt"].endswith("Z")


def test_a_json_fence_around_the_answer_is_accepted(me, monkeypatch):
    Model(monkeypatch, "```json\n" + answer("Fenced.") + "\n```")
    assert ask(me).json()["reply"] == "Fenced."


# ---- changes ---------------------------------------------------------------------------------------


def test_create_one_card_with_every_field(me, monkeypatch):
    board = get_board(me)
    ali = member(board, "Ali")
    Model(monkeypatch, answer("Created it.", [{"type": "create_card", "column": "review", "title": " Plan the launch ", "details": "Pick a date", "priority": "high", "due_date": "2026-12-01", "labels": ["docs", "bug"], "members": [ali]}]))
    body = ask(me, "Add a card").json()
    assert body["applied"] == [{"type": "create_card", "cardId": body["applied"][0]["cardId"], "title": "Plan the launch", "column": "review"}]
    after = body["board"]
    created = after["cards"][body["applied"][0]["cardId"]]
    assert created == {"id": created["id"], "title": "Plan the launch", "details": "Pick a date", "priority": "high", "dueDate": "2026-12-01", "labelIds": ["docs", "bug"], "memberIds": [ali], "progress": 0}
    assert order(after, "review")[-1] == "Plan the launch" and list(after["cards"])[-1] == created["id"]
    assert after == get_board(me)  # the board in the answer is the stored one


def test_create_several_cards(me, monkeypatch):
    actions = [{"type": "create_card", "column": c, "title": f"Card in {c}"} for c in ("ideas", "todo", "doing")]
    Model(monkeypatch, answer("Three cards.", actions))
    body = ask(me).json()
    assert [a["title"] for a in body["applied"]] == ["Card in ideas", "Card in todo", "Card in doing"]
    assert len(body["board"]["cards"]) == 13


def test_every_change_leaves_a_by_ai_event_in_its_cards_room(me, monkeypatch):
    board = get_board(me)
    target, other_card = card(board, "Column unit tests")["id"], card(board, "Jalali date picker")["id"]
    Model(monkeypatch, answer("Done.", [
        {"type": "create_card", "column": "todo", "title": "Fresh"},
        {"type": "update_card", "card_id": target, "priority": "high"},
        {"type": "move_card", "card_id": other_card, "column": "review"},
    ]))
    body = ask(me).json()
    after = body["board"]
    fresh = body["applied"][0]["cardId"]
    me_id = after["currentUserId"]
    by = lambda space: [(e["event"], e["byAi"], e["authorId"]) for e in events(after, space) if e["byAi"]]
    assert by(fresh) == [("created", True, me_id)]
    assert by(target) == [("updated", True, me_id)]
    assert by(other_card) == [("moved", True, me_id)]
    assert [e for e in events(after, other_card) if e["event"] == "moved"][-1]["columnId"] == "review"
    assert all(not e["byAi"] for e in events(get_board(me), card(board, "Task chat room")["id"]))  # other rooms untouched


def test_update_fields_labels_members_progress_and_clear_the_date(me, monkeypatch):
    board = get_board(me)
    target = card(board, "Task chat room")["id"]  # has a due date, two labels, three members
    ali, reza = member(board, "Ali"), member(board, "Reza")
    Model(monkeypatch, answer("Updated.", [{"type": "update_card", "card_id": target, "title": "Chat rooms", "details": "New text", "priority": "low", "due_date": "", "labels": ["bug"], "members": [ali, reza], "progress": 80}]))
    body = ask(me).json()
    changed = body["board"]["cards"][target]
    assert (changed["title"], changed["details"], changed["priority"], changed["dueDate"], changed["labelIds"], changed["progress"]) == ("Chat rooms", "New text", "low", None, ["bug"], 80)
    assert set(changed["memberIds"]) == {ali, reza}  # the other two were removed, Ali was added
    kinds = [e["event"] for e in events(body["board"], target) if e["byAi"]]
    assert kinds.count("updated") == 1 and kinds.count("added") == 1 and kinds.count("removed") == 2
    assert body["applied"][0]["fields"] == ["details", "dueDate", "labelIds", "members", "priority", "progress", "title"]


def test_null_fields_leave_things_as_they_are(me, monkeypatch):
    board = get_board(me)
    target = card(board, "Task chat room")
    Model(monkeypatch, answer("Only the priority.", [{"type": "update_card", "card_id": target["id"], "title": None, "details": None, "priority": "high", "due_date": None, "labels": None, "members": None, "progress": None}]))
    after = ask(me).json()["board"]["cards"][target["id"]]
    assert after == {**target, "priority": "high"}


def test_members_already_on_the_card_are_not_added_twice(me, monkeypatch):
    board = get_board(me)
    target = card(board, "Drag and drop cards")
    Model(monkeypatch, answer("Same people.", [{"type": "update_card", "card_id": target["id"], "members": target["memberIds"]}]))
    body = ask(me).json()
    assert body["applied"][0]["type"] == "update_card"
    assert [e for e in events(body["board"], target["id"]) if e["byAi"] and e["event"] in ("added", "removed")] == []


def test_move_to_another_column_at_a_position(me, monkeypatch):
    board = get_board(me)
    target = card(board, "Column unit tests")["id"]
    Model(monkeypatch, answer("Moved.", [{"type": "move_card", "card_id": target, "column": "done", "position": 0}]))
    after = ask(me).json()["board"]
    assert order(after, "done") == ["Column unit tests", "Set up Next.js project", "Write AGENTS.md"]


def test_move_without_a_position_goes_to_the_end_and_a_reorder_is_logged_too(me, monkeypatch):
    board = get_board(me)
    first = card(board, "Drag and drop cards")["id"]
    Model(monkeypatch, answer("Reordered.", [{"type": "move_card", "card_id": first, "column": "doing"}]))  # same column, to the end
    after = ask(me).json()["board"]
    assert order(after, "doing") == ["Jalali date picker", "Task chat room", "Drag and drop cards"]
    assert [(e["event"], e["byAi"]) for e in events(after, first) if e["byAi"]] == [("updated", True)]  # no "moved": the column is the same


def test_later_actions_see_the_effect_of_earlier_ones(me, monkeypatch):
    board = get_board(me)
    target = card(board, "Column unit tests")["id"]
    Model(monkeypatch, answer("Two steps.", [
        {"type": "move_card", "card_id": target, "column": "doing"},
        {"type": "update_card", "card_id": target, "progress": 10},
    ]))
    after = ask(me).json()["board"]
    assert target in column(after, "doing")["cardIds"] and after["cards"][target]["progress"] == 10


# ---- when the answer is not usable: nothing changes ---------------------------------------------------

BAD_ANSWERS = {
    "not JSON at all": "Sure! I added the card.",
    "broken JSON": '{"reply": "x", "actions": [',
    "JSON that is not an object": '["a", "b"]',
    "no reply": json.dumps({"actions": []}),
    "empty reply": json.dumps({"reply": "", "actions": []}),
    "actions is not a list": json.dumps({"reply": "x", "actions": "create a card"}),
    "unknown action type": answer("x", [{"type": "delete_card", "card_id": "x"}]),
    "an action without its type": answer("x", [{"column": "todo", "title": "T"}]),
    "an unknown field": answer("x", [{"type": "create_card", "column": "todo", "title": "T", "colour": "red"}]),
    "a missing field": answer("x", [{"type": "create_card", "column": "todo"}]),
    "an empty title": answer("x", [{"type": "create_card", "column": "todo", "title": ""}]),
    "a bad priority": answer("x", [{"type": "create_card", "column": "todo", "title": "T", "priority": "urgent"}]),
    "progress above 100": answer("x", [{"type": "update_card", "card_id": "x", "progress": 101}]),
    "too many actions": answer("x", [{"type": "create_card", "column": "todo", "title": f"T{i}"} for i in range(assistant.MAX_ACTIONS + 1)]),
    "a column that does not exist": answer("x", [{"type": "create_card", "column": "backlog", "title": "T"}]),
    "a label that does not exist": answer("x", [{"type": "create_card", "column": "todo", "title": "T", "labels": ["urgent"]}]),
    "a member that does not exist": answer("x", [{"type": "create_card", "column": "todo", "title": "T", "members": ["nobody"]}]),
    "an impossible date": answer("x", [{"type": "create_card", "column": "todo", "title": "T", "due_date": "2026-13-45"}]),
    "a date in words": answer("x", [{"type": "create_card", "column": "todo", "title": "T", "due_date": "next Friday"}]),
}


@pytest.mark.parametrize("bad", BAD_ANSWERS.values(), ids=BAD_ANSWERS.keys())
def test_an_unusable_answer_changes_nothing_and_returns_a_plain_message(me, monkeypatch, bad):
    before = json.dumps(get_board(me), sort_keys=True)
    Model(monkeypatch, bad)
    response = ask(me, "Add a card please")
    assert response.status_code == 200  # no crash
    body = response.json()
    assert body["reply"] == assistant.NOT_CHANGED["en"] and body["applied"] == [] and body["problem"]
    assert json.dumps(get_board(me), sort_keys=True) == before == json.dumps(body["board"], sort_keys=True)


def test_the_plain_message_is_in_the_users_language(me, monkeypatch):
    Model(monkeypatch, "not json")
    assert ask(me, "یک کارت بساز").json()["reply"] == assistant.NOT_CHANGED["fa"]
    assert ask(me, "Make a card").json()["reply"] == assistant.NOT_CHANGED["en"]


def test_a_card_id_that_does_not_exist_changes_nothing(me, monkeypatch):
    before = json.dumps(get_board(me), sort_keys=True)
    Model(monkeypatch, answer("x", [{"type": "update_card", "card_id": "00000000-0000-0000-0000-000000000000", "title": "Ghost"}]))
    body = ask(me).json()
    assert "no card with id" in body["problem"] and body["reply"] == assistant.NOT_CHANGED["en"]
    assert json.dumps(get_board(me), sort_keys=True) == before


def test_one_bad_action_cancels_all_the_good_ones(me, monkeypatch):
    board = get_board(me)
    target = card(board, "Column unit tests")["id"]
    before = json.dumps(board, sort_keys=True)
    Model(monkeypatch, answer("Three things.", [
        {"type": "create_card", "column": "todo", "title": "Would be created"},
        {"type": "move_card", "card_id": target, "column": "done"},
        {"type": "move_card", "card_id": "no-such-card", "column": "done"},  # the third is wrong
    ]))
    body = ask(me).json()
    assert "action 3" in body["problem"]
    after = get_board(me)
    assert json.dumps(after, sort_keys=True) == before  # not the card, not the move, not a single event
    assert "Would be created" not in json.dumps(after)


def test_a_failure_halfway_through_applying_rolls_everything_back(me, monkeypatch, db_file):
    board = get_board(me)
    before = json.dumps(board, sort_keys=True)
    history_before = json.dumps(me.get("/api/ai/history").json())
    Model(monkeypatch, answer("Create, then move.", [
        {"type": "create_card", "column": "todo", "title": "Created first"},
        {"type": "update_card", "card_id": card(board, "Column unit tests")["id"], "priority": "high"},
        {"type": "move_card", "card_id": card(board, "Task chat room")["id"], "column": "done"},
    ]))

    def explode(*args, **kwargs):
        raise RuntimeError("the database failed halfway")

    monkeypatch.setattr(board_service, "move_card", explode)  # the third change blows up after two were applied
    quiet = TestClient(app, raise_server_exceptions=False)
    quiet.cookies.update(me.cookies)
    assert ask(quiet).status_code == 500
    monkeypatch.undo()
    assert json.dumps(get_board(me), sort_keys=True) == before
    assert json.dumps(me.get("/api/ai/history").json()) == history_before


def test_a_database_refusal_during_apply_is_also_a_plain_message_and_changes_nothing(me, monkeypatch):
    import sqlite3

    before = json.dumps(get_board(me), sort_keys=True)
    Model(monkeypatch, answer("Create.", [{"type": "create_card", "column": "todo", "title": "Created"}, {"type": "move_card", "card_id": card(get_board(me), "Task chat room")["id"], "column": "done"}]))

    def refuse(*args, **kwargs):
        raise sqlite3.IntegrityError("CHECK constraint failed")

    monkeypatch.setattr(board_service, "move_card", refuse)
    body = ask(me).json()
    assert body["reply"] == assistant.NOT_CHANGED["en"] and body["applied"] == []
    monkeypatch.undo()
    assert json.dumps(get_board(me), sort_keys=True) == before


def test_the_card_of_another_users_board_is_not_reachable(me, other, monkeypatch):
    theirs = card(get_board(other), "Task chat room")["id"]
    before_mine, before_theirs = json.dumps(get_board(me), sort_keys=True), json.dumps(get_board(other), sort_keys=True)
    Model(monkeypatch, answer("x", [{"type": "update_card", "card_id": theirs, "title": "Hijacked"}]))
    assert "no card with id" in ask(me).json()["problem"]
    assert json.dumps(get_board(me), sort_keys=True) == before_mine and json.dumps(get_board(other), sort_keys=True) == before_theirs


def test_a_deleted_card_cannot_be_edited(me, monkeypatch):
    gone = card(get_board(me), "Column unit tests")["id"]
    me.delete(f"/api/cards/{gone}")
    Model(monkeypatch, answer("x", [{"type": "update_card", "card_id": gone, "title": "Zombie"}]))
    assert "no card with id" in ask(me).json()["problem"]


def test_the_failed_exchange_is_remembered_so_the_conversation_makes_sense(me, monkeypatch):
    Model(monkeypatch, "nonsense")
    ask(me, "Do something")
    history = me.get("/api/ai/history").json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["content"] == assistant.NOT_CHANGED["en"] and history[1]["changes"]["applied"] == [] and history[1]["changes"]["problem"]


# ---- the service misbehaves ------------------------------------------------------------------------


def use_client(monkeypatch, client: FakeClient):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-0123456789")
    monkeypatch.setattr(ai, "_client", lambda: client)
    return client


@pytest.mark.parametrize("status", [429, 503])
def test_a_busy_service_is_retried_once_and_then_works(me, monkeypatch, sleeps, status):
    client = use_client(monkeypatch, FakeClient(outcomes=[status_error(status), answer("Second try worked.")]))
    response = ask(me)
    assert response.status_code == 200 and response.json()["reply"] == "Second try worked."
    assert len(client.calls) == 2 and sleeps == [ai.RETRY_DELAY_SECONDS]


@pytest.mark.parametrize("status", [429, 503])
def test_a_service_that_stays_busy_gives_a_clear_bilingual_message_and_changes_nothing(me, monkeypatch, sleeps, status):
    before = snapshot(me)
    client = use_client(monkeypatch, FakeClient(error=status_error(status)))
    response = ask(me)
    assert response.status_code == 503  # no crash
    assert response.json() == {"detail": {"en": assistant.BUSY["en"], "fa": assistant.BUSY["fa"]}}
    assert "busy" in response.json()["detail"]["en"] and "مشغول" in response.json()["detail"]["fa"]
    assert len(client.calls) == 2 and len(sleeps) == 1
    assert snapshot(me) == before  # the board and the history are untouched


@pytest.mark.parametrize("error", [status_error(500), status_error(401), openai.APITimeoutError(request=REQUEST), openai.APIConnectionError(request=REQUEST)])
def test_other_service_failures_are_a_clear_bilingual_502(me, monkeypatch, error):
    before = snapshot(me)
    use_client(monkeypatch, FakeClient(error=error))
    response = ask(me)
    assert response.status_code == 502
    assert response.json() == {"detail": {"en": assistant.FAILED["en"], "fa": assistant.FAILED["fa"]}}
    assert snapshot(me) == before


def test_without_a_key_it_says_so_in_both_languages_and_the_app_still_works(me):
    response = ask(me)
    assert response.status_code == 503 and response.json() == {"detail": {"en": "AI is not configured", "fa": "هوش مصنوعی پیکربندی نشده است"}}
    assert get_board(me)["cards"] and me.get("/api/ai/history").json() == []


def test_the_chat_routes_need_sign_in_and_a_message(client, me):
    anonymous = TestClient(app)
    assert anonymous.post("/api/ai/chat", json={"message": "hi"}).status_code == 401
    assert anonymous.get("/api/ai/history").status_code == 401
    assert me.post("/api/ai/chat", json={}).status_code == 422
    assert me.post("/api/ai/chat", json={"message": ""}).status_code == 422
    assert me.post("/api/ai/chat", json={"message": "   "}).status_code == 422
    assert me.post("/api/ai/chat", json={"message": "x" * 4001}).status_code == 422


def test_the_key_is_never_in_an_answer_or_in_the_prompt(me, monkeypatch):
    secret = "test-key-0123456789"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    model = Model(monkeypatch, answer("ok"))
    response = ask(me)
    assert secret not in response.text and secret not in json.dumps(model.calls)
    assert secret not in me.get("/api/ai/history").text


# ---- the board shows by_ai events ------------------------------------------------------------------


def test_the_event_is_marked_as_the_assistants_in_the_board(me, monkeypatch):
    target = card(get_board(me), "Column unit tests")["id"]
    Model(monkeypatch, answer("Moved.", [{"type": "move_card", "card_id": target, "column": "review"}]))
    ask(me)
    moved = [e for e in get_board(me)["messages"][target] if e.get("event") == "moved"]
    assert moved[-1]["byAi"] is True and moved[-1]["columnId"] == "review"
    assert name(get_board(me)["members"][moved[-1]["authorId"]]["name"]) == "Atefe Kalamati"  # the user asked, the AI did it
