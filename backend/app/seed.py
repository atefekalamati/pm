"""The Tidy sample board, created in one transaction at a user's first sign-in.

A Python copy of frontend/data/seed.ts. Sample text comes in two languages: (English, Persian).
The seed's `sara` seat is the signed-in user (Atefe Kalamati); the others are the team users who cannot sign in.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from app.db import new_id, now_iso, tx

STEP = 1024  # gap between card positions in a column, see docs/DATABASE.md section 3

LABELS = [
    ("design", "Design", "طراحی"),
    ("frontend", "Frontend", "فرانت‌اند"),
    ("bug", "Bug", "باگ"),
    ("docs", "Docs", "مستندات"),
    ("testing", "Testing", "تست"),
]

COLUMNS = [("ideas", None), ("todo", None), ("doing", 3), ("review", 2), ("done", None)]

# id, column, title, details, priority, labels, members, progress, due in N days (None = no date)
CARDS = [
    ("c1", "ideas", ("Board progress bar", "نوار پیشرفت تخته"),
     ("Show the share of finished cards in the board header.", "نمایش درصد کارت‌های انجام‌شده در سربرگ تخته."),
     "low", ["design"], ["maryam"], 0, None),
    ("c2", "ideas", ("Keyboard shortcut sheet", "راهنمای میانبرها"),
     ("Open a cheat sheet with the ? key.", "باز شدن راهنما با کلید ?"),
     "low", ["frontend"], [], 0, None),
    ("c3", "todo", ("Empty column state", "طراحی حالت خالی ستون"),
     ("A friendly message and quick add when a column has no cards.", "پیام دوستانه و افزودن سریع وقتی ستونی کارت ندارد."),
     "high", ["design"], ["sara"], 10, 3),
    ("c4", "todo", ("Column unit tests", "تست‌های واحد ستون‌ها"),
     ("Cover add, delete and rename with Vitest.", "پوشش افزودن، حذف و تغییر نام با Vitest."),
     "medium", ["testing"], ["ali"], 0, 8),
    ("c5", "doing", ("Drag and drop cards", "کشیدن و رها کردن کارت‌ها"),
     ("dnd-kit with keyboard support and a drop indicator line.", "پیاده‌سازی با dnd-kit همراه با صفحه‌کلید و خط محل فرود."),
     "high", ["frontend"], ["ali", "sara"], 60, 0),
    ("c6", "doing", ("Jalali date picker", "انتخابگر تاریخ شمسی"),
     ("Wire react-multi-date-picker to the Persian calendar.", "اتصال react-multi-date-picker به تقویم شمسی."),
     "medium", ["frontend"], ["maryam"], 35, -2),
    ("c7", "doing", ("Task chat room", "اتاق گفتگوی کار"),
     ("Group chat per task with images, members and progress updates.", "گفتگوی گروهی برای هر کار، با عکس، اعضا و گزارش پیشرفت."),
     "medium", ["design", "frontend"], ["sara", "reza", "maryam"], 45, 1),
    ("c8", "review", ("Fix mixed text direction", "اصلاح جهت متن ترکیبی"),
     ("Persian text keeps its own direction inside the English UI.", "متن فارسی در رابط انگلیسی جهت خودش را حفظ کند."),
     "high", ["bug"], ["sara"], 90, 2),
    ("c9", "done", ("Set up Next.js project", "راه‌اندازی پروژه Next.js"),
     ("Scaffold, Tailwind and .gitignore.", "ساختار اولیه، Tailwind و ‎.gitignore"),
     "low", ["docs"], ["reza"], 100, -7),
    ("c10", "done", ("Write AGENTS.md", "نوشتن AGENTS.md"),
     ("Requirements, palette and delivery plan.", "نیازمندی‌ها، پالت رنگ و راهبرد اجرا."),
     "medium", ["docs"], ["sara"], 100, -12),
]

# space ("general" or a card id above), then messages as dicts. time is the original clock time.
MESSAGES = {
    "general": [
        dict(author="reza", time="09:02", text=("Morning team! Standup notes are in the Docs cards.", "صبح بخیر تیم! یادداشت‌های جلسه‌ی صبح در کارت‌های مستندات است.")),
        dict(author="sara", time="09:10", task="c7"),
        dict(author="maryam", time="09:24", image="empty-states-moodboard.png", text=("Moodboard for the empty column states", "مودبورد حالت‌های خالی ستون")),
        dict(author="ali", time="09:31", text=("Drag and drop is at 60%. Keyboard moves are next.", "کشیدن و رها کردن ۶۰٪ پیش رفته. قدم بعدی جابه‌جایی با صفحه‌کلید است.")),
        dict(author="sara", time="09:33", text=("Great progress. Let us review it together after lunch.", "عالیه. بعد از ناهار با هم مرورش کنیم.")),
    ],
    "c7": [
        dict(author="sara", time="09:11", event="added", member="reza"),
        dict(author="sara", time="09:11", event="added", member="maryam"),
        dict(author="maryam", time="10:05", image="chat-panel-v1.png", text=("First layout for the chat panel.", "اولین چیدمان پنل گفتگو.")),
        dict(author="reza", time="10:12", text=("Looks clean. Can progress updates show as small events in the thread?", "تمیز شده. می‌شود گزارش‌های پیشرفت را به شکل رویدادهای کوچک در گفتگو نشان داد؟")),
        dict(author="sara", time="10:20", event="progress", value=45),
        dict(author="sara", time="10:21", text=("Done. Next up: image upload in the composer.", "انجام شد. قدم بعدی: آپلود عکس در کادر پیام.")),
    ],
    "c5": [
        dict(author="ali", time="08:40", text=("Pointer drag works across all columns.", "کشیدن با موس بین همه‌ی ستون‌ها کار می‌کند.")),
        dict(author="ali", time="08:41", event="progress", value=60),
    ],
}

# The demo shows 2 unread in General and 1 in the task room: these are the last messages the owner has read.
LAST_READ = {"general": 1, "c7": 2}  # index into the space's messages


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def create_board(conn: sqlite3.Connection, owner_id: str, now: datetime | None = None) -> str:
    """Creates a board for the user with the sample data (or returns the one they already have); returns the board id."""
    now = now or datetime.now(timezone.utc)
    created = now_iso(now)
    team = {username: row["id"] for username, row in
            ((u, conn.execute("SELECT id FROM users WHERE username = ?", (u,)).fetchone()) for u in ("ali", "maryam", "reza"))
            if row}
    seat = {"sara": owner_id, **team}  # the seed's "sara" is the signed-in user
    # Sample message times keep their spacing but end shortly before creation, so none is in the future.
    first_clock = now - timedelta(hours=3) - timedelta(minutes=8 * 60)

    with tx(conn):
        # Checked inside the transaction: two first sign-ins at the same moment must still make one board.
        existing = conn.execute("SELECT board_id FROM board_members WHERE user_id = ? AND role = 'owner'", (owner_id,)).fetchone()
        if existing:
            return existing["board_id"]
        board = new_id()
        conn.execute("INSERT INTO boards (id, created_at) VALUES (?, ?)", (board, created))
        conn.execute("INSERT INTO board_members VALUES (?, ?, 'owner', 1)", (board, owner_id))
        for position, user_id in enumerate(team.values(), start=2):
            conn.execute("INSERT INTO board_members VALUES (?, ?, 'member', ?)", (board, user_id, position))

        columns = {}
        for position, (slug, wip) in enumerate(COLUMNS, start=1):
            columns[slug] = new_id()
            conn.execute("INSERT INTO columns (id, board_id, slug, position, wip_limit) VALUES (?, ?, ?, ?, ?)",
                         (columns[slug], board, slug, position, wip))
        labels = {}
        for position, (slug, name, name_fa) in enumerate(LABELS, start=1):
            labels[slug] = new_id()
            conn.execute("INSERT INTO labels (id, board_id, slug, name, name_fa, position) VALUES (?, ?, ?, ?, ?, ?)",
                         (labels[slug], board, slug, name, name_fa, position))

        spaces = {"general": new_id()}
        conn.execute("INSERT INTO spaces (id, board_id, kind, created_at) VALUES (?, ?, 'general', ?)", (spaces["general"], board, created))

        cards = {}
        per_column: dict[str, int] = {}
        for seq, (key, column, title, details, priority, card_labels, members, progress, due_in) in enumerate(CARDS, start=1):
            cards[key] = new_id()
            per_column[column] = per_column.get(column, 0) + 1
            due = (now + timedelta(days=due_in)).date().isoformat() if due_in is not None else None
            conn.execute(
                "INSERT INTO cards (id, board_id, column_id, position, seq, title, title_fa, details, details_fa, priority, due_date, progress, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cards[key], board, columns[column], per_column[column] * STEP, seq, title[0], title[1], details[0], details[1], priority, due, progress, created),
            )
            spaces[key] = new_id()
            conn.execute("INSERT INTO spaces (id, board_id, kind, card_id, created_at) VALUES (?, ?, 'card', ?, ?)", (spaces[key], board, cards[key], created))
            for position, slug in enumerate(card_labels, start=1):
                conn.execute("INSERT INTO card_labels VALUES (?, ?, ?)", (cards[key], labels[slug], position))
            for position, member in enumerate(members, start=1):
                conn.execute("INSERT INTO card_members VALUES (?, ?, ?)", (cards[key], seat[member], position))

        for space_key, messages in MESSAGES.items():
            ids = []
            for m in messages:
                at = now_iso(first_clock + timedelta(minutes=_minutes(m["time"])))
                text, text_fa = m.get("text", (None, None))
                kind = "task" if "task" in m else "event" if "event" in m else "message"
                cur = conn.execute(
                    "INSERT INTO messages (space_id, author_id, kind, text, text_fa, event, event_value, event_member_id, card_id, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (spaces[space_key], seat[m["author"]], kind, text, text_fa, m.get("event"), m.get("value"),
                     seat[m["member"]] if "member" in m else None, cards[m["task"]] if "task" in m else None, at),
                )
                ids.append(cur.lastrowid)
                if "image" in m:  # sample images have no pixels: a row without bytes shows as a placeholder
                    conn.execute("INSERT INTO images (id, board_id, uploader_id, message_id, file_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                                 (new_id(), board, seat[m["author"]], cur.lastrowid, m["image"], created))
            read_to = ids[LAST_READ[space_key]] if space_key in LAST_READ else ids[-1]
            conn.execute("INSERT INTO space_reads VALUES (?, ?, ?)", (owner_id, spaces[space_key], read_to))
    return board
