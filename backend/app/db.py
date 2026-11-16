"""SQLite access: connection settings, schema migrations and housekeeping. See docs/DATABASE.md."""

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Request

from app.security import hash_password

BASE_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BASE_DIR / "migrations"
RETENTION = timedelta(hours=24)  # how long a deleted card (for Undo) or an unattached upload is kept


def db_path() -> Path:
    return Path(os.environ.get("DATABASE_PATH", BASE_DIR / "data" / "tidy.db"))


def now_iso(moment: datetime | None = None) -> str:
    """UTC ISO 8601 with milliseconds and a Z, e.g. 2026-11-15T08:30:00.000Z. Sorts correctly as text."""
    moment = (moment or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def new_id() -> str:
    return str(uuid.uuid4())


def connect(path: Path | str) -> sqlite3.Connection:
    # Autocommit mode: transactions are explicit (see tx). One connection per request, used by one thread at a time.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite defaults to OFF; without it no ON DELETE rule works
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def tx(conn: sqlite3.Connection):
    """One write transaction: commits on success, rolls back on any error.

    Inside a transaction that is already open it joins that one instead (SQLite cannot nest), so several
    changes can be made together: the outermost `tx` commits all of them or, on any error, none.
    """
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def get_db(request: Request):
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


# ---- migrations ------------------------------------------------------------------------------------


def migrate(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR, db_file: Path | str | None = None) -> int:
    """Applies migrations/NNNN_*.sql newer than PRAGMA user_version, each in its own transaction.

    A new database is simply version 0 upgraded to the latest. An existing one is copied to
    <file>.bak-v<N> first. A database newer than the newest file is refused.
    """
    files = sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    latest = int(files[-1].name[:4]) if files else 0
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > latest:
        raise RuntimeError(f"The database is at schema version {current}, newer than this app ({latest}). Update the app.")
    pending = [f for f in files if int(f.name[:4]) > current]
    if pending and current > 0 and db_file:
        backup = sqlite3.connect(f"{db_file}.bak-v{current}")
        try:
            conn.backup(backup)
        finally:
            backup.close()
    for file in pending:
        version = int(file.name[:4])
        try:
            conn.executescript(f"BEGIN;\n{file.read_text(encoding='utf-8')}\nPRAGMA user_version = {version};\nCOMMIT;")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return conn.execute("PRAGMA user_version").fetchone()[0]


# ---- first-run data and housekeeping ---------------------------------------------------------------

TEAM = [  # username, name, name_fa, initials, initials_fa, can sign in
    ("user", "Atefe Kalamati", "عاطفه کلماتی", "AK", "عک", True),
    ("ali", "Ali Rezaei", "علی رضایی", "AR", "عر", False),
    ("maryam", "Maryam Karimi", "مریم کریمی", "MK", "مک", False),
    ("reza", "Reza Mohammadi", "رضا محمدی", "RM", "رم", False),
]


def seed_users(conn: sqlite3.Connection) -> None:
    """Only `user` / `password` can sign in; the other team members have no password hash."""
    if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return
    with tx(conn):
        for username, name, name_fa, initials, initials_fa, can_sign_in in TEAM:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, name, name_fa, initials, initials_fa, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id(), username, hash_password("password") if can_sign_in else None, name, name_fa, initials, initials_fa, now_iso()),
            )


def purge(conn: sqlite3.Connection, now: datetime | None = None) -> dict[str, int]:
    """Removes what has outlived its use. Runs at startup and with every card delete; there is no scheduled job.

    - cards deleted more than 24 h ago (the cascade removes their room, messages, announcements and images),
    - uploaded images that never got a message, older than 24 h,
    - expired sessions.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now_iso(now - RETENTION)
    with tx(conn):
        cards = conn.execute("DELETE FROM cards WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,)).rowcount
        images = conn.execute("DELETE FROM images WHERE message_id IS NULL AND created_at < ?", (cutoff,)).rowcount
        sessions = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso(now),)).rowcount
    return {"cards": cards, "images": images, "sessions": sessions}


def init_db(path: Path | str, directory: Path = MIGRATIONS_DIR) -> None:
    """Creates the file when missing, upgrades the schema, adds the team users and purges."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")  # persistent, so once is enough
        migrate(conn, directory, path)
        seed_users(conn)
        purge(conn)
    finally:
        conn.close()
