# Frontend (Tidy)

A bilingual (English / Persian, LTR / RTL) Kanban board with a team chat. Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4. It is a client-only app built as a static export (`output: "export"` in `next.config.ts`, output in `out/`), which FastAPI serves at `/`. Sign-in goes through the backend; the board data itself still lives in the browser (`localStorage`) until Part 7.

Static export rules: no server-only features (Route Handlers that read the request, Server Actions, `cookies()`, `headers()`, default `next/image` loader). `cacheComponents` and `partialPrefetching` are off because they enable PPR, which `next build` rejects in export mode.

## Structure

- `app/` - `layout.tsx` (fonts: Geist, Geist Mono, Vazirmatn; metadata), `page.tsx` (client-only shell: sign-in page when signed out, otherwise Sidebar + Header + Board or Chat, dialogs, undo toast, storage recovery screen), `globals.css` (Tailwind theme and the palette).
- `components/` - `Board` (dnd-kit context, mouse and keyboard drag), `Column` (rename, WIP limit, collapse), `Card`, `CardDialog` (create / edit card), `Sidebar` (navigation, task rooms, ⋯ account menu with Sign out), `SignIn` (sign-in page with its own language switch), `Header` (breadcrumb, language, density), `Chat` / `Conversation` / `TaskPanel` (general room and one room per card, images, progress, members), `HelpDialog`, `UndoToast`, `JalaliDatePicker`, `Dialog`, `ui` (shared small parts, including the `Logo`).
- `lib/` - `store.ts` (all state and actions), `session.ts` (sign-in state and `api()`, see below), `types.ts` (data model), `migration.ts` (V1 -> V3 upgrade of saved data), `i18n/`, `utils.ts` (dates, numbers), `compressImage.ts` (uploads resized to 1280px, max 2 MB), `useShortcuts.ts` (keyboard shortcuts).
- `data/seed.ts` - sample members, labels, cards and messages; `CURRENT_USER_ID`, `GENERAL_SPACE`, `MAX_IMAGE_BYTES`.

## Store

`lib/store.ts` is one Zustand store with `persist` (key `kanban-store`, version 3). Components must read and write data only through it, so it can be pointed at the backend API later.

- Data: `columns` (5 fixed ids: `ideas`, `todo`, `doing`, `review`, `done`; optional custom `name`, `cardIds`, `wipLimit`, `collapsed`), `cards`, `members`, `messages` per space (`general` or a card id), `unread`.
- UI state: `language`, `density`, `view`, `activeSpace` (persisted); `dialog`, `lastDeleted` (not persisted).
- Actions: `addCard`, `updateCard`, `deleteCard`, `undoDelete`, `dismissUndo`, `moveCard`, `moveCardBy`, `setProgress`, `postProgress`, `addMember`, `removeMember`, `sendMessage`, `createTaskFromMessage`, `renameColumn`, `setWipLimit`, `toggleColumn`, `setLanguage`, `setDensity`, `setView`, `openSpace`, `openRoom`, `openDialog`, `closeDialog`.
- Uploaded images are stored inline as data URLs inside messages. Before migration the raw old data is backed up (`kanban-store-v1-backup`); if loading fails, `page.tsx` shows the recovery screen.

## Session

`lib/session.ts` is a small in-memory Zustand store (`checking` / `signed-in` / `signed-out`, plus the user from `/api/me`); the session itself is an HttpOnly cookie. Call the backend only through `api()`: any `401` ends the session, closes dialogs and shows the sign-in page. `page.tsx` checks `/api/me` on load, on tab focus or visibility, on a Back/Forward cache restore and every minute. In `npm run dev`, `next.config.ts` rewrites `/api/*` to the backend on `localhost:8000`.

## i18n

`lib/i18n/en.ts` and `fa.ts` are plain dictionaries with the same keys (checked by `i18n.test.ts`). `useT()` returns `t` (strings), `L` (resolves sample text stored as `{ en, fa }`; user text is a plain string and never translated), `n` / `pct` (localized digits), `date` (Jalali display; dates are stored as Gregorian `yyyy-MM-dd`) and `columnName`. `page.tsx` sets `lang` and `dir` on `<html>`. Layout uses only logical CSS properties (`ms-*`, `pe-*`, `start`, `end`).

## Palette: Linen Sky

Defined once in `app/globals.css` as role-named variables inside `@theme` (`--color-page`, `--color-surface`, `--color-primary` `#2f6fa8`, `--color-heading` `#1e3a5f`, priority, due date, label and avatar colors, column accents `--accent-*`). Use the Tailwind classes made from these roles (`bg-page`, `text-heading`, `bg-primary`); do not write hex values in components. Note: this palette replaces the color list in the root `AGENTS.md`.

## Tests

- Unit (Vitest + Testing Library, jsdom): `npm test`. Files sit next to the code (`*.test.ts(x)`); `vitest.setup.ts` clears `localStorage` and resets the store before each test.
- End-to-end (Playwright, Chromium at 1860x900): `npx playwright test`. Specs in `e2e/` (`auth`, `board`, `chat`, `sidebar`, shared `helpers.ts`). The shared `test` signs in through the API (`login()`) before each test; `auth.spec.ts` starts signed out. The config starts the backend (`uv run uvicorn` on 8000) and `npm run dev` on port 3000, or reuses them if already running. To test the Docker container instead, start it and set `PLAYWRIGHT_BASE_URL=http://localhost:8000`; no dev server is started then.
- Also: `npm run lint`, `npm run build` (writes `out/`).

<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
