import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from helpers import count, new_card, upload

from app import db
from app.seed import create_board

OLD = "2000-01-01T00:00:00.000Z"


def test_a_missing_database_is_created_with_tables_and_users(tmp_path):
    path = tmp_path / "nested" / "new.db"
    assert not path.exists()
    db.init_db(path)
    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} >= {"users", "cards", "messages", "images"}
    users = {r["username"]: r["password_hash"] for r in conn.execute("SELECT username, password_hash FROM users")}
    assert set(users) == {"user", "ali", "maryam", "reza"}
    assert users["user"] and not any(users[u] for u in ("ali", "maryam", "reza"))


def test_starting_again_keeps_the_data(tmp_path):
    path = tmp_path / "tidy.db"
    db.init_db(path)
    conn = db.connect(path)
    conn.execute("UPDATE users SET name = 'Changed' WHERE username = 'ali'")
    db.init_db(path)
    assert conn.execute("SELECT name FROM users WHERE username = 'ali'").fetchone()[0] == "Changed"
    assert count(conn, "users") == 4


def test_wal_mode_and_foreign_keys_on_every_connection(db_file, client):
    assert db.connect(db_file).execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    for _ in range(3):
        conn = db.connect(db_file)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_a_column_that_still_has_cards_cannot_be_deleted(me, conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM columns WHERE slug = 'doing'")


def test_deleting_a_board_removes_all_of_its_data(me, conn):
    conn.execute("DELETE FROM boards")
    for table in ("columns", "labels", "cards", "card_labels", "card_members", "spaces", "messages", "images", "space_reads", "board_members"):
        assert count(conn, table) == 0, table
    assert count(conn, "users") == 4
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_user_with_history_cannot_be_deleted(me, conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM users WHERE username = 'ali'")


def test_purge_removes_cards_deleted_over_24_hours_ago_with_everything_inside(me, conn):
    task = me.post("/api/spaces/general/tasks", json={"text": "Old news"}).json()  # a card plus its announcement in General
    card = task["card"]
    me.post(f"/api/spaces/{card['id']}/messages", json={"text": "hello"})
    me.post(f"/api/cards/{card['id']}/post-progress")
    me.post(f"/api/spaces/{card['id']}/read")
    stays = new_card(me, "Stays")
    room = conn.execute("SELECT id FROM spaces WHERE card_id = ?", (card["id"],)).fetchone()[0]
    me.delete(f"/api/cards/{card['id']}")
    before = {t: count(conn, t) for t in ("cards", "spaces", "messages", "card_members", "space_reads")}

    assert db.purge(conn) == {"cards": 0, "images": 0, "sessions": 0}  # deleted a moment ago: still undoable
    conn.execute("UPDATE cards SET deleted_at = ? WHERE id = ?", (OLD, card["id"]))
    assert db.purge(conn)["cards"] == 1

    after = {t: count(conn, t) for t in before}
    assert {t: before[t] - after[t] for t in before} == {
        "cards": 1,
        "spaces": 1,  # its room
        "messages": 3,  # "hello", the progress event, and the announcement in General
        "card_members": 1,  # the creator
        "space_reads": 1,
    }
    assert count(conn, "space_reads", "space_id = ?", (room,)) == 0
    assert count(conn, "cards", "id = ?", (stays["id"],)) == 1  # other cards are untouched
    assert me.post(f"/api/cards/{card['id']}/restore").status_code == 404  # too late for Undo


def test_purge_runs_at_startup(db_file):
    db.init_db(db_file)
    conn = db.connect(db_file)
    create_board(conn, conn.execute("SELECT id FROM users WHERE username = 'user'").fetchone()[0])
    conn.execute("UPDATE cards SET deleted_at = ? WHERE title = 'Task chat room'", (OLD,))
    db.init_db(db_file)  # the next server start
    assert count(conn, "cards") == 9


def test_purge_runs_with_every_delete_and_needs_no_scheduler(me, conn):
    first = new_card(me, "First")
    second = new_card(me, "Second")
    assert me.delete(f"/api/cards/{first['id']}").status_code == 204
    conn.execute("UPDATE cards SET deleted_at = ? WHERE id = ?", (OLD, first["id"]))
    assert count(conn, "cards", "id = ?", (first["id"],)) == 1  # old enough, but nothing has purged yet
    me.delete(f"/api/cards/{second['id']}")  # the next delete does it
    assert count(conn, "cards", "id = ?", (first["id"],)) == 0
    assert count(conn, "cards", "id = ?", (second["id"],)) == 1  # the new one stays for Undo


def test_purge_removes_only_old_unattached_images_and_expired_sessions(me, conn):
    old, new, attached = upload(me)["id"], upload(me)["id"], upload(me)["id"]
    me.post("/api/spaces/general/messages", json={"imageId": attached})
    conn.execute("UPDATE images SET created_at = ? WHERE id IN (?, ?)", (OLD, old, attached))
    conn.execute("INSERT INTO sessions VALUES ('stale', (SELECT id FROM users WHERE username = 'user'), ?, ?)", (OLD, OLD))
    result = db.purge(conn)
    assert result["images"] == 1 and result["sessions"] == 1
    assert count(conn, "images", "id = ?", (old,)) == 0
    assert count(conn, "images", "id = ?", (new,)) == 1  # a recent upload: its message may still come
    assert count(conn, "images", "id = ?", (attached,)) == 1  # old, but it belongs to a message


def test_purge_uses_the_clock_it_is_given(db_file, client):
    conn = db.connect(db_file)
    assert db.purge(conn, datetime.now(timezone.utc) + timedelta(days=30))["sessions"] == 0
