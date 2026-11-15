# Frontend (Tidy)

A bilingual (English / Persian, LTR / RTL) Kanban board with a team chat. Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4. It is a client-only app built as a static export (`output: "export"` in `next.config.ts`, output in `out/`), which FastAPI serves at `/`. All data lives on the server (SQLite, through `/api`); the browser keeps only light preferences.

Static export rules: no server-only features (Route Handlers that read the request, Server Actions, `cookies()`, `headers()`, default `next/image` loader). `cacheComponents` and `partialPrefetching` are off because they enable PPR, which `next build` rejects in export mode. `npm run dev` rewrites `/api/*` to the backend on `localhost:8000` (dev only, in `next.config.ts`).

## Structure

- `app/` - `layout.tsx` (fonts: Geist, Geist Mono, Vazirmatn; metadata), `page.tsx` (the shell, see "Store and the server"), `globals.css` (Tailwind theme and the palette).
- `components/` - `Board` (dnd-kit context, mouse and keyboard drag), `Column` (rename, WIP limit, collapse), `Card`, `CardDialog` (create / edit card), `Sidebar` (navigation, task rooms, account menu with Sign out), `SignIn`, `Header`, `Chat` / `Conversation` / `TaskPanel` (General and one room per card, images, progress, members), `HelpDialog`, `UndoToast`, `NoticeToast`, `BoardSkeleton`, `Unreachable`, `JalaliDatePicker`, `Dialog`, `ui` (shared small parts, including the `Logo`).
- `lib/` - `store.ts` (all state and actions), `api.ts` (every backend call and the server-to-store conversion), `session.ts` (who is signed in), `types.ts` (data model), `i18n/`, `utils.ts` (dates, numbers), `compressImage.ts` (uploads resized to 1280px, max 2 MB; also `dataUrlToBlob`), `useShortcuts.ts` (keyboard shortcuts).
- `data/constants.ts` - `GENERAL_SPACE`, `MAX_IMAGE_BYTES` and the five `labels` (the backend creates the same labels). `data/fixtures.ts` - the sample board as test data only (a copy of `backend/app/seed.py`).

## Store and the server

`lib/store.ts` is one Zustand store. Components read and write data only through it. The server is the source of truth.

- **Loading:** after sign-in `page.tsx` calls `loadBoard()`. `boardStatus` is `idle` / `loading` / `ready` / `error`; until it is `ready` the page shows `BoardSkeleton` (no data, so no sample or empty board can flash), and on `error` (or a failing first `/api/me`) it shows `Unreachable` with a Try again button. `lib/api.ts` `parseBoard` converts the server's board (message `createdAt` UTC becomes the local `time` HH:mm, a null column name becomes "show the default").
- **Every action shows its change at once and then sends it** (optimistic). Changes go through one queue, one at a time and in order (a card must exist on the server before it can be moved). New cards, tasks and messages get their id on the client (a UUID the server accepts), so the screen needs no id swap. A burst of progress changes on one card merges into its latest value.
- **A failed change is undone:** if the server refuses it or the connection drops, the screen is restored to how it was before that change, the changes queued behind it are dropped (they were built on it), the undo snapshot is cleared, `notice` is set (the `NoticeToast`, in both languages) and the board is fetched again to be sure screen and server agree. A 401 is different: `lib/api.ts` ends the session and the sign-in page takes over.
- **Images:** the picture is compressed in the browser as before, then sent as a file (the request body of `POST /api/images?fileName=...`, with its type as Content-Type), and only then the message that names it (`imageId`). The compressed picture stays on screen until the next load.
- **Unread** is computed by the server; opening a conversation clears it on screen and tells the server. **Language and density** are user settings on the server (`PATCH /api/settings`). A language picked on the sign-in page is saved after sign-in.
- `whenIdle()` resolves when nothing is waiting to be sent; the app also sets `data-saving` on `<html>` so tests can wait before a reload.
- **In the browser** only `view`, `activeSpace` and `language` are kept (`localStorage` key `tidy-ui`): the last open screen, and the language for the sign-in page. Never data.
- `reset()` (sign-out, ended session) clears everything of the user.

## Session

`lib/session.ts` is a small in-memory Zustand store (`checking` / `signed-in` / `signed-out` / `unreachable`, plus the user from `/api/me`); the session itself is an HttpOnly cookie. Call the backend only through `api()` / `request()` in `lib/api.ts` (`request` throws on a failure so the store can undo). `page.tsx` checks `/api/me` on load, on tab focus or visibility, on a Back/Forward cache restore and every minute.

## i18n

`lib/i18n/en.ts` and `fa.ts` are plain dictionaries with the same keys (checked by `i18n.test.ts`). `useT()` returns `t` (strings), `L` (resolves sample text stored as `{ en, fa }`; text a user writes is a plain string and never translated), `n` / `pct` (localized digits), `date` (Jalali display; dates are stored as Gregorian `yyyy-MM-dd`) and `columnName`. `page.tsx` sets `lang` and `dir` on `<html>`. Layout uses only logical CSS properties (`ms-*`, `pe-*`, `start`, `end`).

## Palette: Linen Sky

Defined once in `app/globals.css` as role-named variables inside `@theme` (`--color-page`, `--color-surface`, `--color-primary` `#2f6fa8`, `--color-heading` `#1e3a5f`, priority, due date, label and avatar colors, column accents `--accent-*`). Use the Tailwind classes made from these roles (`bg-page`, `text-heading`, `bg-primary`); do not write hex values in components. Note: this palette replaces the color list in the root `AGENTS.md`.

## Tests

- **Unit** (Vitest + Testing Library, jsdom): `npm test`. Files sit next to the code. `vitest.setup.ts` loads the sample board (`data/fixtures.ts`) into the store before each test and installs a fake server (`vitest.server.ts`): every request is recorded (`sent()`), succeeds by default, and `failRequests(part, status | "network")` makes some fail, so rollback can be tested. A test's own requests are awaited with `whenIdle()`.
- **End-to-end** (Playwright, Chromium at 1860x900, timezone UTC): `npx playwright test`. Specs in `e2e/`: `board`, `chat`, `sidebar`, `auth`, `persistence` (every kind of change survives a refresh, sign-out/in, a new browser; and, run in two phases around a restart, a container restart), `rollback` (a mocked failing server: refused or dropped, in both languages, plus the loading skeleton and the unreachable page), `isolation` (a second user never sees the first user's board).
- **Test users:** Playwright tests share one server, so each test makes its own user through `POST /api/e2e/users`, which exists only when the server runs with `TIDY_E2E=1` (`helpers.ts` `createUser` / `login`). The dev-server run starts the backend itself in that mode with its own database (`backend/data/e2e.db`). To test the Docker container use a separate one so your real database stays clean:
  `$env:TIDY_PORT="8001"; $env:TIDY_E2E="1"; docker compose -p tidy-e2e up -d --build --wait`, then `$env:PLAYWRIGHT_BASE_URL="http://localhost:8001"; npx playwright test`, then `docker compose -p tidy-e2e down -v`.
- **Container restart check:** with that container running, `PERSIST_PHASE=write PERSIST_USER=restart-check` and `-g "container restart"`, then `docker compose -p tidy-e2e down` and `up -d --wait` (without `-v`), then the same with `PERSIST_PHASE=verify`.
- Also: `npm run lint`, `npm run build` (writes `out/`).

<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
