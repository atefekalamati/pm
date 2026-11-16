"""The AI assistant: it reads the board and a question, and answers with a reply and, when asked, changes to the board.

The model's answer is untrusted text. It is parsed and checked (Pydantic, then against the real board) BEFORE anything
is written, and all its changes are applied in one transaction: every one of them, or none. When the answer is not
usable, the board does not change and the user gets a plain message instead.
"""

import json
import re
import sqlite3
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import ai, board
from app.db import now_iso, tx

HISTORY_LIMIT = 20  # only the last messages are sent to the model, so a request never grows without bound
MAX_ACTIONS = 20
END = 10**9  # "the end of the column", for the move helper (it clamps)

Priority = Literal["low", "medium", "high"]


# ---- what the model may answer ---------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a field we do not know means the answer is not what we asked for


class CreateCard(_Strict):
    type: Literal["create_card"]
    column: str
    title: str = Field(min_length=1, max_length=500)
    details: str = Field(default="", max_length=20000)
    priority: Priority = "medium"
    due_date: str | None = None
    labels: list[str] = []
    members: list[str] = []


class UpdateCard(_Strict):
    """Only fields that are sent (not null) change. due_date "" removes the date; labels and members replace the list."""

    type: Literal["update_card"]
    card_id: str
    title: str | None = Field(default=None, min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=20000)
    priority: Priority | None = None
    due_date: str | None = None
    labels: list[str] | None = None
    members: list[str] | None = None
    progress: int | None = Field(default=None, ge=0, le=100)


class MoveCard(_Strict):
    type: Literal["move_card"]
    card_id: str
    column: str
    position: int | None = Field(default=None, ge=0)  # place in the column, 0 = top; null = the end


Action = Annotated[CreateCard | UpdateCard | MoveCard, Field(discriminator="type")]


class AiReply(_Strict):
    reply: str = Field(min_length=1, max_length=4000)
    actions: list[Action] | None = Field(default=None, max_length=MAX_ACTIONS)


class InvalidAiOutput(Exception):
    """The model's answer cannot be used. The message says why, for the developer; the user gets a plain sentence."""


# ---- messages in both languages --------------------------------------------------------------------

PERSIAN_LETTERS = re.compile("[؀-ۿ]")


def language_of(text: str) -> Literal["en", "fa"]:
    """The assistant answers in the language the user writes in: Persian when the text has Persian letters."""
    return "fa" if PERSIAN_LETTERS.search(text) else "en"


NOT_CHANGED = {
    "en": "I could not make that change because my answer was not valid, so nothing was changed. Please try asking in another way.",
    "fa": "نتوانستم این تغییر را انجام دهم چون پاسخ من معتبر نبود، بنابراین هیچ چیز تغییر نکرد. لطفاً به شکل دیگری بپرسید.",
}
BUSY = {
    "en": "The AI assistant is busy right now. Nothing was changed. Please try again in a moment.",
    "fa": "دستیار هوش مصنوعی اکنون مشغول است. هیچ چیز تغییر نکرد. لطفاً کمی بعد دوباره تلاش کنید.",
}
FAILED = {
    "en": "The AI assistant could not answer (the service reported a problem). Nothing was changed.",
    "fa": "دستیار هوش مصنوعی نتوانست پاسخ دهد (سرویس مشکلی گزارش کرد). هیچ چیز تغییر نکرد.",
}
NOT_CONFIGURED = {"en": "AI is not configured", "fa": "هوش مصنوعی پیکربندی نشده است"}


def unavailable_message(error: ai.AiUnavailable) -> dict[str, str]:
    return BUSY if error.status in ai.RETRY_STATUSES else FAILED


# ---- reading the answer ----------------------------------------------------------------------------


def parse_reply(text: str) -> AiReply:
    """The model's text -> a checked AiReply. Tolerates a ```json fence around it; nothing else."""
    cleaned = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        raise InvalidAiOutput("the answer is not valid JSON") from None
    try:
        return AiReply.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        place = ".".join(str(part) for part in first["loc"])
        raise InvalidAiOutput(f"the answer does not match the expected format ({place}: {first['msg']})") from None


def check_actions(conn: sqlite3.Connection, board_id: str, actions: list) -> None:
    """Every id and column the model used must exist on THIS board. Raises before anything is changed."""
    columns = {r["slug"] for r in conn.execute("SELECT slug FROM columns WHERE board_id = ?", (board_id,))}
    labels = {r["slug"] for r in conn.execute("SELECT slug FROM labels WHERE board_id = ?", (board_id,))}
    members = {r["user_id"] for r in conn.execute("SELECT user_id FROM board_members WHERE board_id = ?", (board_id,))}
    cards = {r["id"] for r in conn.execute("SELECT id FROM cards WHERE board_id = ? AND deleted_at IS NULL", (board_id,))}

    for n, a in enumerate(actions, start=1):
        where = f"action {n} ({a.type})"
        if a.type != "create_card" and a.card_id not in cards:
            raise InvalidAiOutput(f"{where}: there is no card with id {a.card_id!r}")
        if a.type in ("create_card", "move_card") and a.column not in columns:
            raise InvalidAiOutput(f"{where}: there is no column {a.column!r} (columns: {', '.join(sorted(columns))})")
        if a.type in ("create_card", "update_card"):
            for slug in a.labels or []:
                if slug not in labels:
                    raise InvalidAiOutput(f"{where}: there is no label {slug!r}")
            for user_id in a.members or []:
                if user_id not in members:
                    raise InvalidAiOutput(f"{where}: {user_id!r} is not a member of this board")
            if a.due_date:
                try:
                    date.fromisoformat(a.due_date)
                except ValueError:
                    raise InvalidAiOutput(f"{where}: due_date {a.due_date!r} is not a date like 2026-11-20") from None
        if a.type == "update_card":
            changes = a.model_dump(exclude={"type", "card_id"}, exclude_none=True)
            if not changes:
                raise InvalidAiOutput(f"{where}: nothing to change")


# ---- applying the changes --------------------------------------------------------------------------


def _log(conn: sqlite3.Connection, user_id: str, card_id: str, event: str, **fields) -> None:
    board.log_event(conn, board.card_space_id(conn, card_id), user_id, event, by_ai=True, **fields)


def apply_actions(conn: sqlite3.Connection, board_id: str, user_id: str, actions: list) -> list[dict]:
    """Runs inside the caller's transaction, with the same functions the screen uses. Each change leaves a by_ai event in its card's room."""
    applied = []
    for a in actions:
        if a.type == "create_card":
            data = {"title": a.title.strip(), "details": a.details, "priority": a.priority, "dueDate": a.due_date or None, "labelIds": a.labels, "memberIds": a.members}
            created = board.create_card(conn, board_id, a.column, data)
            _log(conn, user_id, created["id"], "created")
            applied.append({"type": "create_card", "cardId": created["id"], "title": a.title.strip(), "column": a.column})

        elif a.type == "update_card":
            changes = {}
            for field, key in (("title", "title"), ("details", "details"), ("priority", "priority"), ("progress", "progress"), ("labels", "labelIds")):
                value = getattr(a, field)
                if value is not None:
                    changes[key] = value.strip() if field == "title" else value
            if a.due_date is not None:
                changes["dueDate"] = a.due_date or None  # "" removes the date
            if changes:
                board.update_card(conn, board_id, a.card_id, changes)
                _log(conn, user_id, a.card_id, "updated")
            if a.members is not None:
                current = [r["user_id"] for r in conn.execute("SELECT user_id FROM card_members WHERE card_id = ?", (a.card_id,))]
                for user in [u for u in a.members if u not in current]:
                    board.add_member(conn, board_id, user_id, a.card_id, user, by_ai=True)
                for user in [u for u in current if u not in a.members]:
                    board.remove_member(conn, board_id, user_id, a.card_id, user, by_ai=True)
            applied.append({"type": "update_card", "cardId": a.card_id, "fields": sorted([*changes, *(["members"] if a.members is not None else [])])})

        else:  # move_card
            before = conn.execute("SELECT column_id FROM cards WHERE id = ?", (a.card_id,)).fetchone()["column_id"]
            board.move_card(conn, board_id, user_id, a.card_id, a.column, END if a.position is None else a.position, by_ai=True)
            after = conn.execute("SELECT column_id FROM cards WHERE id = ?", (a.card_id,)).fetchone()["column_id"]
            if before == after:  # a reorder inside a column has no "moved" event, so say it with a general one
                _log(conn, user_id, a.card_id, "updated")
            applied.append({"type": "move_card", "cardId": a.card_id, "column": a.column})
    return applied


# ---- the question ----------------------------------------------------------------------------------


def today() -> date:
    return datetime.now(timezone.utc).date()


RULES = """You are the assistant of a Kanban project board called Tidy. You can read the board below and change it when the user asks.

Answer with ONE JSON object and nothing else (no text around it):
{"reply": "<what you say to the user>", "actions": [ ... ]}

LANGUAGE: write "reply", and any title or details you create, in the language of the user's LATEST message (Persian or English).
Only change the board when the user asks for a change; for a question or chat, use "actions": [].

Each action is one of:
{"type": "create_card", "column": "<column slug>", "title": "...", "details": "", "priority": "low|medium|high", "due_date": "YYYY-MM-DD or null", "labels": ["<label slug>"], "members": ["<member id>"]}
{"type": "update_card", "card_id": "<card id>", "title": null, "details": null, "priority": null, "due_date": null, "labels": null, "members": null, "progress": null}
   (null means "leave as it is"; send only what changes. due_date "" removes the date. labels and members replace the whole list. progress is 0-100.)
{"type": "move_card", "card_id": "<card id>", "column": "<column slug>", "position": null}
   (position is the place in that column, 0 = top; null = the end)

Rules:
- Use only card ids, member ids, label slugs and column slugs that appear in the board below. Never invent one.
- Columns are exactly: ideas, todo, doing, review, done.
- If you cannot do what is asked (for example the card does not exist), do not guess: explain in "reply" and send "actions": [].
- Always answer in this JSON format, even if earlier replies in the conversation look like plain text.
- Today is {today}."""


def board_snapshot(conn: sqlite3.Connection, board_id: str, user_id: str) -> dict:
    """The board as the model should see it: cards, columns, labels, members. No chat messages, no images."""
    full = board.load_board(conn, board_id, user_id)
    placement = {card_id: (c["id"], index) for c in full["columns"] for index, card_id in enumerate(c["cardIds"])}
    return {
        "columns": [{"slug": c["id"], "name": c["name"], "card_ids": c["cardIds"]} for c in full["columns"]],
        "cards": [
            {
                "id": c["id"], "title": c["title"], "details": c["details"], "priority": c["priority"], "due_date": c["dueDate"],
                "progress": c["progress"], "column": placement[c["id"]][0], "position": placement[c["id"]][1],
                "labels": c["labelIds"], "members": c["memberIds"],
            }
            for c in full["cards"].values()
        ],
        "labels": [{"slug": label["id"], "name": label["name"]} for label in full["labels"]],
        "members": [{"id": m["id"], "name": m["name"]} for m in full["members"].values()],
    }


def history_rows(conn: sqlite3.Connection, board_id: str, user_id: str, limit: int = HISTORY_LIMIT) -> list[sqlite3.Row]:
    rows = conn.execute(
        "SELECT id, role, content, changes, created_at FROM ai_messages WHERE board_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
        (board_id, user_id, limit),
    ).fetchall()
    return rows[::-1]


def build_messages(conn: sqlite3.Connection, board_id: str, user_id: str, question: str) -> list[dict]:
    system = RULES.replace("{today}", today().isoformat()) + "\n\nCurrent board (JSON):\n" + json.dumps(board_snapshot(conn, board_id, user_id), ensure_ascii=False, separators=(",", ":"))
    history = [{"role": r["role"], "content": r["content"]} for r in history_rows(conn, board_id, user_id)]
    return [{"role": "system", "content": system}, *history, {"role": "user", "content": question}]


def _remember(conn: sqlite3.Connection, board_id: str, user_id: str, question: str, reply: str, applied: list[dict], problem: str | None) -> None:
    for role, content, changes in (("user", question, None), ("assistant", reply, json.dumps({"applied": applied, "problem": problem}, ensure_ascii=False))):
        conn.execute(
            "INSERT INTO ai_messages (board_id, user_id, role, content, changes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (board_id, user_id, role, content, changes, now_iso()),
        )


def chat(conn: sqlite3.Connection, board_id: str, user_id: str, question: str) -> dict:
    """Asks the model and applies what it answers. Raises ai.AiNotConfigured / ai.AiUnavailable; those change and store nothing."""
    messages = build_messages(conn, board_id, user_id, question)
    raw = ai.complete(messages, response_format={"type": "json_object"})  # slow: no transaction is open while waiting

    try:
        answer = parse_reply(raw)
        with tx(conn):  # checks, changes and history succeed together or not at all
            actions = answer.actions or []
            check_actions(conn, board_id, actions)
            applied = apply_actions(conn, board_id, user_id, actions)
            _remember(conn, board_id, user_id, question, answer.reply, applied, None)
        reply, problem = answer.reply, None
    except (InvalidAiOutput, HTTPException, sqlite3.Error) as error:
        # Nothing was changed (the transaction above rolled back). Only a plain message goes back.
        problem = str(error.detail) if isinstance(error, HTTPException) else str(error)
        reply, applied = NOT_CHANGED[language_of(question)], []
        with tx(conn):
            _remember(conn, board_id, user_id, question, reply, [], str(problem))

    return {"reply": reply, "applied": applied, "problem": problem, "board": board.load_board(conn, board_id, user_id)}


def history(conn: sqlite3.Connection, board_id: str, user_id: str) -> list[dict]:
    return [
        {"id": r["id"], "role": r["role"], "content": r["content"], "changes": json.loads(r["changes"]) if r["changes"] else None, "createdAt": r["created_at"]}
        for r in history_rows(conn, board_id, user_id)
    ]
