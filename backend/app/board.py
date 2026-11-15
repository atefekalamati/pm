"""Board logic: reading the whole board and every change to it. No HTTP here, so the AI (Part 9) can reuse it.

Every function that writes opens its own transaction (db.tx). `slug`s are exposed as ids for columns and
labels (ideas, todo, ..., design, bug, ...) because the frontend keys them that way.
"""

import sqlite3
import uuid
from datetime import date

from fastapi import HTTPException

from app.db import new_id, now_iso, purge, tx
from app.seed import STEP

SPACE_GENERAL = "general"


def text(value: str | None, value_fa: str | None):
    """The stored pair as the frontend's `Text`: a plain string, or { en, fa } for sample data."""
    if value is None:
        return None
    return value if value_fa is None else {"en": value, "fa": value_fa}


def bad(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


# ---- reading ---------------------------------------------------------------------------------------


def board_id_of(conn: sqlite3.Connection, user_id: str) -> str | None:
    row = conn.execute(
        "SELECT board_id FROM board_members WHERE user_id = ? ORDER BY role = 'owner' DESC LIMIT 1", (user_id,)
    ).fetchone()
    return row["board_id"] if row else None


def is_member(conn: sqlite3.Connection, board_id: str, user_id: str) -> bool:
    return conn.execute("SELECT 1 FROM board_members WHERE board_id = ? AND user_id = ?", (board_id, user_id)).fetchone() is not None


def user_json(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": text(row["name"], row["name_fa"]), "initials": text(row["initials"], row["initials_fa"])}


def columns_json(conn: sqlite3.Connection, board_id: str) -> list[dict]:
    cards: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT id, column_id FROM cards WHERE board_id = ? AND deleted_at IS NULL ORDER BY position, seq", (board_id,)
    ):
        cards.setdefault(row["column_id"], []).append(row["id"])
    return [
        {"id": c["slug"], "name": c["name"], "cardIds": cards.get(c["id"], []), "wipLimit": c["wip_limit"], "collapsed": bool(c["collapsed"])}
        for c in conn.execute("SELECT id, slug, name, wip_limit, collapsed FROM columns WHERE board_id = ? ORDER BY position", (board_id,))
    ]


def cards_json(conn: sqlite3.Connection, board_id: str, card_id: str | None = None) -> dict[str, dict]:
    """Live cards in creation order (the order of the rooms list), keyed by id."""
    only = " AND c.id = ?" if card_id else ""
    args = (board_id, card_id) if card_id else (board_id,)
    labels: dict[str, list[str]] = {}
    for r in conn.execute("SELECT cl.card_id, l.slug FROM card_labels cl JOIN labels l ON l.id = cl.label_id WHERE l.board_id = ? ORDER BY cl.position", (board_id,)):
        labels.setdefault(r["card_id"], []).append(r["slug"])
    members: dict[str, list[str]] = {}
    for r in conn.execute("SELECT m.card_id, m.user_id FROM card_members m JOIN cards c ON c.id = m.card_id WHERE c.board_id = ? ORDER BY m.position", (board_id,)):
        members.setdefault(r["card_id"], []).append(r["user_id"])
    rows = conn.execute(
        f"SELECT c.* FROM cards c WHERE c.board_id = ? AND c.deleted_at IS NULL{only} ORDER BY c.seq", args
    )
    return {
        r["id"]: {
            "id": r["id"], "title": text(r["title"], r["title_fa"]), "details": text(r["details"], r["details_fa"]) or "",
            "priority": r["priority"], "dueDate": r["due_date"], "labelIds": labels.get(r["id"], []),
            "memberIds": members.get(r["id"], []), "progress": r["progress"],
        }
        for r in rows
    }


def message_json(r: sqlite3.Row) -> dict:
    m: dict = {"id": str(r["id"]), "type": r["kind"], "authorId": r["author_id"], "createdAt": r["created_at"]}
    if r["kind"] == "message":
        if r["text"] is not None:
            m["text"] = text(r["text"], r["text_fa"])
        if r["image_id"]:
            m["image"] = {"file": r["file_name"]}
            if r["mime_type"]:  # sample images have no bytes and show as a placeholder
                m["image"]["src"] = f"/api/images/{r['image_id']}"
    elif r["kind"] == "event":
        m["event"] = r["event"]
        m["byAi"] = bool(r["by_ai"])
        if r["event_value"] is not None:
            m["value"] = r["event_value"]
        if r["event_member_id"]:
            m["memberId"] = r["event_member_id"]
        if r["event_column_slug"]:
            m["columnId"] = r["event_column_slug"]
    else:
        m["cardId"] = r["card_id"]
    return m


MESSAGE_SELECT = """
SELECT m.id, m.kind, m.author_id, m.text, m.text_fa, m.event, m.event_value, m.event_member_id, m.by_ai, m.created_at, m.card_id,
       s.kind AS space_kind, s.card_id AS room_card_id, col.slug AS event_column_slug,
       i.id AS image_id, i.file_name, i.mime_type
FROM messages m
JOIN spaces s ON s.id = m.space_id
LEFT JOIN cards room ON room.id = s.card_id
LEFT JOIN cards task ON task.id = m.card_id
LEFT JOIN columns col ON col.id = m.event_column_id
LEFT JOIN images i ON i.message_id = m.id
"""
# A deleted card's room and its "task created" announcement stay hidden until Undo or the purge.
VISIBLE = "(room.id IS NULL OR room.deleted_at IS NULL) AND (task.id IS NULL OR task.deleted_at IS NULL)"


def space_key(row: sqlite3.Row) -> str:
    return SPACE_GENERAL if row["space_kind"] == "general" else row["room_card_id"]


def messages_json(conn: sqlite3.Connection, board_id: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in conn.execute(f"{MESSAGE_SELECT} WHERE s.board_id = ? AND {VISIBLE} ORDER BY m.id", (board_id,)):
        out.setdefault(space_key(r), []).append(message_json(r))
    return out


def unread_json(conn: sqlite3.Connection, board_id: str, user_id: str) -> dict[str, int]:
    """Messages after the user's read marker, written by someone else. One range query per board."""
    out: dict[str, int] = {}
    rows = conn.execute(
        """
        SELECT s.kind AS space_kind, s.card_id AS room_card_id, count(m.id) AS n
        FROM spaces s
        JOIN messages m ON m.space_id = s.id
        LEFT JOIN space_reads r ON r.space_id = s.id AND r.user_id = :user
        LEFT JOIN cards room ON room.id = s.card_id
        LEFT JOIN cards task ON task.id = m.card_id
        WHERE s.board_id = :board AND m.id > COALESCE(r.last_read_message_id, 0) AND m.author_id <> :user AND """
        + VISIBLE
        + " GROUP BY s.id",
        {"user": user_id, "board": board_id},
    )
    for r in rows:
        out[space_key(r)] = r["n"]
    return out


def load_board(conn: sqlite3.Connection, board_id: str, user_id: str) -> dict:
    user = conn.execute("SELECT language, density FROM users WHERE id = ?", (user_id,)).fetchone()
    members = {
        r["id"]: user_json(r)
        for r in conn.execute(
            "SELECT u.* FROM board_members bm JOIN users u ON u.id = bm.user_id WHERE bm.board_id = ? ORDER BY bm.position", (board_id,)
        )
    }
    labels = [
        {"id": r["slug"], "name": text(r["name"], r["name_fa"])}
        for r in conn.execute("SELECT slug, name, name_fa FROM labels WHERE board_id = ? ORDER BY position", (board_id,))
    ]
    return {
        "currentUserId": user_id,
        "language": user["language"],
        "density": user["density"],
        "columns": columns_json(conn, board_id),
        "cards": cards_json(conn, board_id),
        "labels": labels,
        "members": members,
        "messages": messages_json(conn, board_id),
        "unread": unread_json(conn, board_id, user_id),
    }


# ---- lookups used by the changes -------------------------------------------------------------------


def column_row(conn, board_id: str, slug: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM columns WHERE board_id = ? AND slug = ?", (board_id, slug)).fetchone()
    if not row:
        raise not_found("Column")
    return row


def live_card(conn, board_id: str, card_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM cards WHERE id = ? AND board_id = ? AND deleted_at IS NULL", (card_id, board_id)).fetchone()
    if not row:
        raise not_found("Card")
    return row


def space_row(conn, board_id: str, space_id: str) -> sqlite3.Row:
    """`general`, or the id of a live card (each card has a room)."""
    if space_id == SPACE_GENERAL:
        row = conn.execute("SELECT * FROM spaces WHERE board_id = ? AND kind = 'general'", (board_id,)).fetchone()
    else:
        row = conn.execute(
            "SELECT s.* FROM spaces s JOIN cards c ON c.id = s.card_id WHERE s.board_id = ? AND s.card_id = ? AND c.deleted_at IS NULL",
            (board_id, space_id),
        ).fetchone()
    if not row:
        raise not_found("Conversation")
    return row


def check_labels(conn, board_id: str, slugs: list[str]) -> list[str]:
    ids = []
    for slug in slugs:
        row = conn.execute("SELECT id FROM labels WHERE board_id = ? AND slug = ?", (board_id, slug)).fetchone()
        if not row:
            raise bad(f"Unknown label: {slug}")
        if row["id"] not in ids:
            ids.append(row["id"])
    return ids


def check_members(conn, board_id: str, user_ids: list[str]) -> list[str]:
    for user_id in user_ids:
        if not is_member(conn, board_id, user_id):
            raise bad(f"Not a team member: {user_id}")
    return list(dict.fromkeys(user_ids))


def check_due_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise bad("dueDate must be a date like 2026-11-15") from None


def log_event(conn, space_id: str, author_id: str, event: str, *, value=None, member_id=None, column_id=None, by_ai=False) -> int:
    return conn.execute(
        "INSERT INTO messages (space_id, author_id, kind, event, event_value, event_member_id, event_column_id, by_ai, created_at)"
        " VALUES (?, ?, 'event', ?, ?, ?, ?, ?, ?)",
        (space_id, author_id, event, value, member_id, column_id, int(by_ai), now_iso()),
    ).lastrowid


def card_space_id(conn, card_id: str) -> str:
    return conn.execute("SELECT id FROM spaces WHERE card_id = ?", (card_id,)).fetchone()["id"]


def append_position(conn, column_id: str) -> int:
    return conn.execute("SELECT COALESCE(MAX(position), 0) + ? FROM cards WHERE column_id = ?", (STEP, column_id)).fetchone()[0]


# ---- cards -----------------------------------------------------------------------------------------


def _insert_card(conn, board_id, column_slug, data: dict, card_id: str | None = None) -> str:
    """Inside a transaction. Adds the card at the end of its column together with its room."""
    column = column_row(conn, board_id, column_slug)
    if card_id is not None:
        try:
            card_id = str(uuid.UUID(card_id))
        except ValueError:
            raise bad("id must be a UUID") from None
        if conn.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone():
            raise HTTPException(status_code=409, detail="A card with this id already exists")
    card_id = card_id or new_id()
    label_ids = check_labels(conn, board_id, data["labelIds"])
    member_ids = check_members(conn, board_id, data["memberIds"])
    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM cards WHERE board_id = ?", (board_id,)).fetchone()[0]
    now = now_iso()
    conn.execute(
        "INSERT INTO cards (id, board_id, column_id, position, seq, title, details, priority, due_date, progress, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (card_id, board_id, column["id"], append_position(conn, column["id"]), seq, data["title"], data["details"], data["priority"], check_due_date(data["dueDate"]), now),
    )
    conn.execute("INSERT INTO spaces (id, board_id, kind, card_id, created_at) VALUES (?, ?, 'card', ?, ?)", (new_id(), board_id, card_id, now))
    for position, label_id in enumerate(label_ids, start=1):
        conn.execute("INSERT INTO card_labels VALUES (?, ?, ?)", (card_id, label_id, position))
    for position, user_id in enumerate(member_ids, start=1):
        conn.execute("INSERT INTO card_members VALUES (?, ?, ?)", (card_id, user_id, position))
    return card_id


def create_card(conn, board_id: str, column_slug: str, data: dict, card_id: str | None = None) -> dict:
    with tx(conn):
        new = _insert_card(conn, board_id, column_slug, data, card_id)
    return cards_json(conn, board_id, new)[new]


def update_card(conn, board_id: str, card_id: str, changes: dict) -> dict:
    """`changes` holds only the fields to change. Editing a sample text replaces its Persian version too."""
    with tx(conn):
        live_card(conn, board_id, card_id)
        sets, args = [], []
        if "title" in changes:
            sets += ["title = ?", "title_fa = NULL"]
            args.append(changes["title"])
        if "details" in changes:
            sets += ["details = ?", "details_fa = NULL"]
            args.append(changes["details"])
        for field, column in (("priority", "priority"), ("progress", "progress")):
            if field in changes:
                sets.append(f"{column} = ?")
                args.append(changes[field])
        if "dueDate" in changes:
            sets.append("due_date = ?")
            args.append(check_due_date(changes["dueDate"]))
        if sets:
            conn.execute(f"UPDATE cards SET {', '.join(sets)} WHERE id = ?", (*args, card_id))
        if "labelIds" in changes:
            label_ids = check_labels(conn, board_id, changes["labelIds"])
            conn.execute("DELETE FROM card_labels WHERE card_id = ?", (card_id,))
            for position, label_id in enumerate(label_ids, start=1):
                conn.execute("INSERT INTO card_labels VALUES (?, ?, ?)", (card_id, label_id, position))
        if "memberIds" in changes:
            member_ids = check_members(conn, board_id, changes["memberIds"])
            conn.execute("DELETE FROM card_members WHERE card_id = ?", (card_id,))
            for position, user_id in enumerate(member_ids, start=1):
                conn.execute("INSERT INTO card_members VALUES (?, ?, ?)", (card_id, user_id, position))
    return cards_json(conn, board_id, card_id)[card_id]


def delete_card(conn, board_id: str, card_id: str) -> None:
    """Soft delete: Undo can bring it back until the purge removes it for good (see db.purge)."""
    with tx(conn):
        live_card(conn, board_id, card_id)
        conn.execute("UPDATE cards SET deleted_at = ? WHERE id = ?", (now_iso(), card_id))
    purge(conn)


def restore_card(conn, board_id: str, card_id: str) -> dict:
    with tx(conn):
        done = conn.execute("UPDATE cards SET deleted_at = NULL WHERE id = ? AND board_id = ? AND deleted_at IS NOT NULL", (card_id, board_id)).rowcount
        if not done:
            raise not_found("Deleted card")
    return cards_json(conn, board_id, card_id)[card_id]


def renumber_column(conn, column_id: str, exclude_card_id: str | None = None) -> None:
    """Respaces a whole column to 1024, 2048, ... in its current order, in ONE statement.

    Deleted cards are included so a later Undo still lands in the right place. Called only inside the
    transaction of a move, so a failure leaves every position unchanged.
    """
    conn.execute(
        """
        UPDATE cards SET position = n.p FROM (
            SELECT id, ROW_NUMBER() OVER (ORDER BY position, seq) * ? AS p
            FROM cards WHERE column_id = ? AND id IS NOT ?
        ) n WHERE cards.id = n.id
        """,
        (STEP, column_id, exclude_card_id),
    )


def _siblings(conn, column_id: str, card_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, position FROM cards WHERE column_id = ? AND deleted_at IS NULL AND id <> ? ORDER BY position, seq", (column_id, card_id)
    ).fetchall()


def move_card(conn, board_id: str, actor_id: str, card_id: str, column_slug: str, index: int, *, by_ai: bool = False) -> list[dict]:
    """Puts the card at `index` of the target column (counted without the card itself, like the frontend)."""
    with tx(conn):
        card = live_card(conn, board_id, card_id)
        column = column_row(conn, board_id, column_slug)
        siblings = _siblings(conn, column["id"], card_id)
        index = max(0, min(index, len(siblings)))
        same_column = card["column_id"] == column["id"]
        if same_column and [r["id"] for r in conn.execute(
            "SELECT id FROM cards WHERE column_id = ? AND deleted_at IS NULL ORDER BY position, seq", (column["id"],)
        )].index(card_id) == index:
            return columns_json(conn, board_id)

        def gap() -> tuple[int, int | None]:
            lower = siblings[index - 1]["position"] if index > 0 else 0
            return lower, siblings[index]["position"] if index < len(siblings) else None

        lower, upper = gap()
        if upper is not None and upper - lower < 2:  # no whole number fits between the neighbours
            renumber_column(conn, column["id"], card_id)
            siblings = _siblings(conn, column["id"], card_id)
            lower, upper = gap()
        position = lower + STEP if upper is None else (lower + upper) // 2
        conn.execute("UPDATE cards SET column_id = ?, position = ? WHERE id = ?", (column["id"], position, card_id))
        if not same_column:
            log_event(conn, card_space_id(conn, card_id), actor_id, "moved", column_id=column["id"], by_ai=by_ai)
    return columns_json(conn, board_id)


def add_member(conn, board_id: str, actor_id: str, card_id: str, user_id: str, *, by_ai: bool = False) -> dict:
    with tx(conn):
        live_card(conn, board_id, card_id)
        check_members(conn, board_id, [user_id])
        if conn.execute("SELECT 1 FROM card_members WHERE card_id = ? AND user_id = ?", (card_id, user_id)).fetchone():
            raise HTTPException(status_code=409, detail="Already on this card")
        position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM card_members WHERE card_id = ?", (card_id,)).fetchone()[0]
        conn.execute("INSERT INTO card_members VALUES (?, ?, ?)", (card_id, user_id, position))
        log_event(conn, card_space_id(conn, card_id), actor_id, "added", member_id=user_id, by_ai=by_ai)
    return cards_json(conn, board_id, card_id)[card_id]


def remove_member(conn, board_id: str, actor_id: str, card_id: str, user_id: str, *, by_ai: bool = False) -> dict:
    with tx(conn):
        live_card(conn, board_id, card_id)
        if not conn.execute("DELETE FROM card_members WHERE card_id = ? AND user_id = ?", (card_id, user_id)).rowcount:
            raise not_found("Assignee")
        log_event(conn, card_space_id(conn, card_id), actor_id, "removed", member_id=user_id, by_ai=by_ai)
    return cards_json(conn, board_id, card_id)[card_id]


def post_progress(conn, board_id: str, actor_id: str, card_id: str) -> None:
    """Writes the card's current progress into its room (100 when it is in Done), like the frontend."""
    with tx(conn):
        card = live_card(conn, board_id, card_id)
        in_done = conn.execute("SELECT slug FROM columns WHERE id = ?", (card["column_id"],)).fetchone()["slug"] == "done"
        log_event(conn, card_space_id(conn, card_id), actor_id, "progress", value=100 if in_done else card["progress"])


# ---- columns ---------------------------------------------------------------------------------------


def update_column(conn, board_id: str, slug: str, changes: dict) -> list[dict]:
    with tx(conn):
        column = column_row(conn, board_id, slug)
        if "name" in changes:
            name = (changes["name"] or "").strip()
            conn.execute("UPDATE columns SET name = ? WHERE id = ?", (name or None, column["id"]))  # empty = default name
        if "wipLimit" in changes:
            conn.execute("UPDATE columns SET wip_limit = ? WHERE id = ?", (changes["wipLimit"], column["id"]))
        if "collapsed" in changes:
            conn.execute("UPDATE columns SET collapsed = ? WHERE id = ?", (int(changes["collapsed"]), column["id"]))
    return columns_json(conn, board_id)


# ---- conversations ---------------------------------------------------------------------------------


def send_message(conn, board_id: str, author_id: str, space_id: str, body: str | None, image_id: str | None) -> dict:
    body = body if body and body.strip() else None
    if body is None and image_id is None:
        raise bad("A message needs text or an image")
    with tx(conn):
        space = space_row(conn, board_id, space_id)
        message_id = conn.execute(
            "INSERT INTO messages (space_id, author_id, kind, text, created_at) VALUES (?, ?, 'message', ?, ?)",
            (space["id"], author_id, body, now_iso()),
        ).lastrowid
        if image_id is not None:
            attached = conn.execute(
                "UPDATE images SET message_id = ? WHERE id = ? AND board_id = ? AND uploader_id = ? AND message_id IS NULL",
                (message_id, image_id, board_id, author_id),
            ).rowcount
            if not attached:
                raise bad("Image not found or already used")  # rolls the message back too
    return one_message(conn, message_id)


def one_message(conn, message_id: int) -> dict:
    return message_json(conn.execute(f"{MESSAGE_SELECT} WHERE m.id = ?", (message_id,)).fetchone())


def create_task_from_message(conn, board_id: str, author_id: str, space_id: str, body: str) -> dict:
    """A new card in To do (assigned to its creator) plus a "task created" announcement in the source conversation."""
    with tx(conn):
        space = space_row(conn, board_id, space_id)
        card_id = _insert_card(conn, board_id, "todo", {"title": body, "details": "", "priority": "medium", "dueDate": None, "labelIds": [], "memberIds": [author_id]})
        message_id = conn.execute(
            "INSERT INTO messages (space_id, author_id, kind, card_id, created_at) VALUES (?, ?, 'task', ?, ?)",
            (space["id"], author_id, card_id, now_iso()),
        ).lastrowid
    return {"card": cards_json(conn, board_id, card_id)[card_id], "message": one_message(conn, message_id)}


def mark_read(conn, board_id: str, user_id: str, space_id: str) -> None:
    with tx(conn):
        space = space_row(conn, board_id, space_id)
        conn.execute(
            "INSERT INTO space_reads (user_id, space_id, last_read_message_id)"
            " VALUES (?, ?, (SELECT COALESCE(MAX(id), 0) FROM messages WHERE space_id = ?))"
            " ON CONFLICT (user_id, space_id) DO UPDATE SET last_read_message_id = excluded.last_read_message_id",
            (user_id, space["id"], space["id"]),
        )
