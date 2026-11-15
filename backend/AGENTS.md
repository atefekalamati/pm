# Backend

FastAPI app with SQLite (standard library `sqlite3`, no ORM), packages managed with `uv`. The design is in `docs/DATABASE.md` and `docs/schema.json`. Interactive API docs: `http://localhost:8000/docs`.

## Layout

- `app/main.py`: the app. Its startup (lifespan) creates the database file if missing, applies migrations, adds the team users and purges. `GET /api/health` is public. `static/` is mounted at `/` last, so `/api` routes win; in Docker it is the Next.js export.
- `app/db.py`: connections (`foreign_keys=ON`, `busy_timeout`, `synchronous=NORMAL`; WAL is set once at startup), `tx()` (one write transaction), the migration runner, `seed_users`, `purge`, `now_iso` (UTC ISO 8601).
- `migrations/NNNN_*.sql`: applied in order, each in a transaction, tracked by `PRAGMA user_version`. `0001_init.sql` is generated from `docs/schema.json`. An existing database is copied to `<file>.bak-v<N>` before an upgrade; a database newer than the code stops the app. Change the schema with a new migration file and update `docs/schema.json` in the same change: `tests/test_migrations.py` fails if they differ.
- `app/security.py`: scrypt password hashes, SHA-256 token hashes.
- `app/auth.py`: `POST /api/login` (one generic 401 for every failure), `POST /api/logout`, `GET /api/me`, and `current_user`. The cookie `tidy_session` (HttpOnly, SameSite=Lax, 7 days) holds a random token; only its hash is stored in `sessions`. Only `user` / `password` can sign in; the three teammates have no password hash. First sign-in creates the user's board (`create_board` checks inside its own transaction, so two sign-ins at once still make one board).
- `app/seed.py`: the sample board (Python copy of `frontend/data/seed.ts`), created in one transaction.
- `app/board.py`: all board logic as plain functions (no HTTP), so the AI part can reuse them: `load_board`, cards, columns, assignees, messages, tasks, unread. Every writer opens its own transaction. Events take `by_ai` for the assistant.
- `app/images.py`: upload and read. `POST /api/images?fileName=...` takes the image file itself as the request body (JPEG, PNG or WebP as Content-Type, at most 2 MB, so no base64 and no Data URL); the message that uses it names it with `imageId`. Stored as BLOBs.
- `app/api.py`: the routes and request models. Every route except login and health needs sign-in and works only on the signed-in user's own board (`ctx`).
- `app/e2e.py`: **test-only**, registered only when the server starts with `TIDY_E2E=1`: `POST /api/e2e/users` makes a new user (password `password`, named like the sample user) with a fresh sample board dated from a given `today`, so every Playwright test has its own user. Never enabled in a normal run.
- `tests/`: pytest. `conftest.py` gives each test a fresh database (`db_file`, `client`, `me` = signed in, `other` = a second user with their own board, `conn` = a connection for looking inside). Run `uv run pytest` in this folder.

## API (all under /api)

`GET /board` returns the whole state in the frontend's shape: `columns` (id is the slug), `cards`, `labels`, `members`, `messages` per space (`general` or a card id), `unread`, `language`, `density`, `currentUserId`. Messages carry `createdAt` (UTC) instead of the frontend's old `HH:mm`. Sample text is `{ en, fa }`; text written by a user is a plain string.

Changes: `PATCH /settings`, `PATCH /columns/{slug}`, `POST /cards`, `PATCH|DELETE /cards/{id}`, `POST /cards/{id}/restore | move | members | post-progress`, `DELETE /cards/{id}/members/{userId}`, `POST /spaces/{space}/messages | tasks | read`, `POST /images` (the file as the body), `GET /images/{id}`. `POST /cards` and `POST /spaces/{space}/tasks` accept an optional client-chosen `id` / `cardId` (a UUID), so the screen can show the new card before the server answers. Unknown ids are 404, invalid input is 422, no session is 401.

## Rules worth remembering

- Deleting a card only sets `deleted_at`, so Undo (`/restore`) works. `purge()` removes cards deleted over 24 hours ago (with their room, messages and images), unattached uploads over 24 hours old and expired sessions. It runs at startup and with every card delete; there is no scheduled job.
- Card order is a gapped integer `position` (steps of 1024). A move is 1 write in a column and 2 across columns. When no whole number fits between two neighbours the whole column is renumbered in the same transaction (`renumber_column`).
- Unread is computed from `space_reads.last_read_message_id`; nothing is written per message.

In Docker the app runs with `uvicorn app.main:app` on port 8000. `DATABASE_PATH` is `/data/tidy.db` on the `tidy-data` volume (the default outside Docker is `backend/data/tidy.db`, which git ignores); `.env` is read at run time by `docker-compose.yml` and never copied into the image. The `Dockerfile` builds the frontend in a Node stage, then copies `out/` into the image.
