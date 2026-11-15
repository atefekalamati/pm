import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { GENERAL_SPACE } from "@/data/constants";
import { ApiError, json, parseBoard, parseMessage, request, type RawBoard, type RawMessage } from "./api";
import { dataUrlToBlob } from "./compressImage";
import type {
  Card,
  CardInput,
  ChatMessage,
  Column,
  ColumnId,
  DeletedCard,
  Density,
  Dialog,
  Language,
  Member,
  Message,
  SpaceId,
  SystemEvent,
  Text,
  View,
} from "./types";
import { currentTime } from "./utils";

/** idle: not signed in or not asked yet. loading: first load. ready. error: the server could not be reached. */
export type BoardStatus = "idle" | "loading" | "ready" | "error";

const emptyData = () => ({
  columns: [] as Column[],
  cards: {} as Record<string, Card>,
  members: {} as Record<string, Member>,
  messages: {} as Record<SpaceId, Message[]>,
  unread: {} as Record<SpaceId, number>,
  currentUserId: "",
  language: "en" as Language,
  density: "comfortable" as Density,
});

export const initialState = () => ({
  ...emptyData(),
  view: "board" as View,
  activeSpace: GENERAL_SPACE as SpaceId,
  dialog: null as Dialog | null,
  lastDeleted: null as DeletedCard | null,
  /** Set when a change was refused or lost and has been undone; the toast shows it. */
  notice: null as { id: number } | null,
  boardStatus: "idle" as BoardStatus,
  /** The language was picked before sign-in (on the sign-in page), so it should be saved once the board is there. */
  languageChosenEarly: false,
});

type State = ReturnType<typeof initialState>;
type Snapshot = Pick<State, "columns" | "cards" | "members" | "messages" | "unread" | "language" | "density">;

export interface Store extends State {
  addCard: (columnId: ColumnId, input: CardInput) => string;
  updateCard: (id: string, input: CardInput) => void;
  deleteCard: (id: string) => void;
  undoDelete: () => void;
  dismissUndo: () => void;
  moveCard: (cardId: string, toColumnId: ColumnId, toIndex: number) => void;
  moveCardBy: (cardId: string, delta: -1 | 1) => void;
  setProgress: (cardId: string, value: number) => void;
  postProgress: (cardId: string) => void;
  addMember: (cardId: string, memberId: string) => void;
  removeMember: (cardId: string, memberId: string) => void;
  /** Shows the message at once and sends it; an image is uploaded first, as a file. Returns true. */
  sendMessage: (spaceId: SpaceId, content: Pick<ChatMessage, "text" | "image">) => boolean;
  createTaskFromMessage: (spaceId: SpaceId, text: string) => string;
  renameColumn: (id: ColumnId, name: string) => void;
  setWipLimit: (id: ColumnId, limit: number | null) => void;
  toggleColumn: (id: ColumnId) => void;
  setLanguage: (language: Language) => void;
  setDensity: (density: Density) => void;
  setView: (view: View) => void;
  openSpace: (spaceId: SpaceId) => void;
  openRoom: (cardId: string) => void;
  openDialog: (dialog: Dialog) => void;
  closeDialog: () => void;
  dismissNotice: () => void;
  /** First load after sign-in. */
  loadBoard: () => Promise<void>;
  /** Quietly fetches the board again and replaces the screen with the server's truth. */
  refresh: () => Promise<void>;
  /** Forgets everything of the signed-in user (sign-out, ended session). Keeps the light preferences. */
  reset: () => void;
}

export const columnOf = (columns: Column[], cardId: string) =>
  columns.find((c) => c.cardIds.includes(cardId))!;

/** Pure placement of a card; also used for the live preview while dragging. */
export function placeCard(columns: Column[], cardId: string, toColumnId: ColumnId, toIndex: number): Column[] {
  return columns.map((c) => {
    const cardIds = c.cardIds.filter((x) => x !== cardId);
    if (c.id === toColumnId) cardIds.splice(toIndex, 0, cardId);
    return { ...c, cardIds };
  });
}

// ---- sending changes ---------------------------------------------------------------------------------
//
// Every change is shown at once and then sent. Changes go out one at a time and in order (a card must exist on
// the server before it can be moved). If one fails, the screen goes back to how it was before that change, the
// changes queued behind it are dropped (they were built on it), a toast says so, and the board is fetched again
// to be sure screen and server agree.

interface Op {
  snapshot: Snapshot;
  send: () => Promise<void>;
  epoch: number;
  /** Changes with the same key that are still waiting merge into one (a slider sends only its latest value). */
  key?: string;
}

let queue: Op[] = [];
let running = false;
let epoch = 0; // bumped by reset(), so an answer for a signed-out user can never touch the next one
let noticeId = 0;
const idleWaiters: (() => void)[] = [];

const takeSnapshot = (s: State): Snapshot => ({
  columns: s.columns,
  cards: s.cards,
  members: s.members,
  messages: s.messages,
  unread: s.unread,
  language: s.language,
  density: s.density,
});

function showSaving() {
  // Also lets tests wait until everything has reached the server.
  if (typeof document !== "undefined") document.documentElement.dataset.saving = String(running || queue.length > 0);
}

/** Resolves when nothing is waiting to be sent. */
export const whenIdle = () => new Promise<void>((resolve) => (running || queue.length ? idleWaiters.push(resolve) : resolve()));

function enqueue(op: Op) {
  const last = queue.at(-1);
  if (op.key && last?.key === op.key) {
    last.send = op.send; // the newest value wins; the first snapshot stays, so a failure undoes the whole burst
    return;
  }
  queue.push(op);
  void pump();
}

async function pump() {
  if (running) return;
  running = true;
  showSaving();
  try {
    while (queue.length) {
      const op = queue.shift()!;
      try {
        await op.send();
      } catch (error) {
        queue = [];
        if (op.epoch === epoch) rollBack(op.snapshot, error);
      }
    }
  } finally {
    running = false;
    showSaving();
    idleWaiters.splice(0).forEach((resolve) => resolve());
  }
}

function rollBack(snapshot: Snapshot, error: unknown) {
  // A 401 means the session ended: lib/api already sent the user to the sign-in page and cleared the store.
  if (error instanceof ApiError && error.status === 401) return;
  useStore.setState({ ...snapshot, lastDeleted: null, notice: { id: ++noticeId } });
  void useStore.getState().refresh();
}

// ---- helpers -----------------------------------------------------------------------------------------

const plain = (text: Text) => (typeof text === "string" ? text : text.en);
const cardBody = (input: CardInput) => ({
  title: plain(input.title),
  details: plain(input.details),
  priority: input.priority,
  dueDate: input.dueDate,
  labelIds: input.labelIds,
  memberIds: input.memberIds,
});

const stamp = (s: State) => ({ id: crypto.randomUUID(), authorId: s.currentUserId, time: currentTime() });
const event = (s: State, e: SystemEvent) => ({ ...stamp(s), type: "event", ...e }) as Message;

const pushMessage = (messages: State["messages"], spaceId: SpaceId, message: Message) => ({
  ...messages,
  [spaceId]: [...(messages[spaceId] ?? []), message],
});

const markRead = (unread: State["unread"], spaceId: SpaceId) => {
  const { [spaceId]: _read, ...rest } = unread;
  return rest;
};

const send = (path: string, method: string, body?: unknown) => async () => {
  await request(path, { method, body: body === undefined ? undefined : json(body) });
};

// ---- light preferences in the browser ----------------------------------------------------------------
// Only the open view, the open conversation and the language (for the sign-in page). Everything else is on the server.

const lightStorage = createJSONStorage<Pick<State, "view" | "activeSpace" | "language">>(() => ({
  getItem: (key) => window.localStorage.getItem(key),
  removeItem: (key) => window.localStorage.removeItem(key),
  setItem: (key, value) => {
    try {
      window.localStorage.setItem(key, value);
    } catch {
      // Preferences are not worth failing for.
    }
  },
}));

export const useStore = create<Store>()(
  persist(
    (set, get) => {
      /** Shows a change now and sends it. `change` is applied to the state; `delivery` runs in the queue. */
      const commit = (change: Partial<State> | ((s: State) => Partial<State>), delivery: () => Promise<void>, key?: string) => {
        const snapshot = takeSnapshot(get());
        set(change as Partial<Store>);
        enqueue({ snapshot, send: delivery, epoch, key });
      };

      const patchCard = (s: State, id: string, patch: Partial<Card>) => ({ cards: { ...s.cards, [id]: { ...s.cards[id], ...patch } } });

      const applyBoard = (board: ReturnType<typeof parseBoard>) =>
        set((s) => ({
          ...board,
          activeSpace: s.activeSpace === GENERAL_SPACE || board.cards[s.activeSpace] ? s.activeSpace : GENERAL_SPACE,
        }));

      const readSpace = (spaceId: SpaceId) => {
        if (!get().unread[spaceId]) return;
        commit((s) => ({ unread: markRead(s.unread, spaceId) }), send(`/api/spaces/${spaceId}/read`, "POST"));
      };

      return {
        ...initialState(),

        addCard: (columnId, input) => {
          const id = crypto.randomUUID();
          commit(
            (s) => ({
              cards: { ...s.cards, [id]: { ...input, id, progress: 0 } },
              columns: s.columns.map((c) => (c.id === columnId ? { ...c, cardIds: [...c.cardIds, id] } : c)),
            }),
            send("/api/cards", "POST", { id, columnId, ...cardBody(input) }),
          );
          return id;
        },

        updateCard: (id, input) => commit((s) => patchCard(s, id, input), send(`/api/cards/${id}`, "PATCH", cardBody(input))),

        deleteCard: (id) =>
          commit((s) => {
            const { [id]: card, ...cards } = s.cards;
            const { [id]: room, ...rest } = s.messages;
            const column = columnOf(s.columns, id);
            const announcements = Object.entries(rest).flatMap(([spaceId, list]) =>
              list.flatMap((message, index) =>
                message.type === "task" && message.cardId === id ? [{ spaceId, index, message }] : [],
              ),
            );
            const messages = Object.fromEntries(
              Object.entries(rest).map(([space, list]) => [space, list.filter((m) => !(m.type === "task" && m.cardId === id))]),
            );
            return {
              lastDeleted: {
                card,
                columnId: column.id,
                columnIndex: column.cardIds.indexOf(id),
                roomIndex: Object.keys(s.cards).indexOf(id),
                room,
                unread: s.unread[id],
                announcements,
                wasActiveSpace: s.activeSpace === id,
              },
              cards,
              messages,
              unread: markRead(s.unread, id),
              columns: s.columns.map((c) => ({ ...c, cardIds: c.cardIds.filter((x) => x !== id) })),
              activeSpace: s.activeSpace === id ? GENERAL_SPACE : s.activeSpace,
            };
          }, send(`/api/cards/${id}`, "DELETE")),

        undoDelete: () => {
          const deleted = get().lastDeleted;
          if (!deleted) return;
          commit((s) => {
            const { card, columnId, columnIndex, roomIndex, room, unread, announcements, wasActiveSpace } = deleted;

            const entries = Object.entries(s.cards);
            entries.splice(roomIndex, 0, [card.id, card]);

            const messages = room ? { ...s.messages, [card.id]: room } : { ...s.messages };
            for (const { spaceId, index, message } of announcements) {
              const list = [...(messages[spaceId] ?? [])];
              list.splice(index, 0, message);
              messages[spaceId] = list;
            }

            return {
              cards: Object.fromEntries(entries),
              messages,
              unread: unread ? { ...s.unread, [card.id]: unread } : s.unread,
              columns: placeCard(s.columns, card.id, columnId, columnIndex),
              activeSpace: wasActiveSpace && s.activeSpace === GENERAL_SPACE ? card.id : s.activeSpace,
              lastDeleted: null,
            };
          }, send(`/api/cards/${deleted.card.id}/restore`, "POST"));
        },

        dismissUndo: () => set({ lastDeleted: null }),

        moveCard: (cardId, toColumnId, toIndex) => {
          const from = columnOf(get().columns, cardId);
          if (from.id === toColumnId && from.cardIds.indexOf(cardId) === toIndex) return;
          commit(
            (s) => ({
              columns: placeCard(s.columns, cardId, toColumnId, toIndex),
              messages: from.id !== toColumnId ? pushMessage(s.messages, cardId, event(s, { event: "moved", columnId: toColumnId })) : s.messages,
            }),
            send(`/api/cards/${cardId}/move`, "POST", { columnId: toColumnId, index: toIndex }),
          );
        },

        moveCardBy: (cardId, delta) => {
          const { columns, moveCard } = get();
          const target = columns[columns.indexOf(columnOf(columns, cardId)) + delta];
          if (target) moveCard(cardId, target.id, target.cardIds.length);
        },

        setProgress: (cardId, value) =>
          commit((s) => patchCard(s, cardId, { progress: value }), send(`/api/cards/${cardId}`, "PATCH", { progress: value }), `progress:${cardId}`),

        postProgress: (cardId) => {
          const { cards, columns } = get();
          const done = columnOf(columns, cardId).id === "done";
          commit(
            (s) => ({ messages: pushMessage(s.messages, cardId, event(s, { event: "progress", value: done ? 100 : cards[cardId].progress })) }),
            send(`/api/cards/${cardId}/post-progress`, "POST"),
          );
        },

        addMember: (cardId, memberId) =>
          commit(
            (s) => ({
              ...patchCard(s, cardId, { memberIds: [...s.cards[cardId].memberIds, memberId] }),
              messages: pushMessage(s.messages, cardId, event(s, { event: "added", memberId })),
            }),
            send(`/api/cards/${cardId}/members`, "POST", { userId: memberId }),
          ),

        removeMember: (cardId, memberId) =>
          commit(
            (s) => ({
              ...patchCard(s, cardId, { memberIds: s.cards[cardId].memberIds.filter((m) => m !== memberId) }),
              messages: pushMessage(s.messages, cardId, event(s, { event: "removed", memberId })),
            }),
            send(`/api/cards/${cardId}/members/${memberId}`, "DELETE"),
          ),

        sendMessage: (spaceId, content) => {
          const shown = { ...stamp(get()), type: "message", ...content } as Message;
          commit(
            (s) => ({ messages: pushMessage(s.messages, spaceId, shown) }),
            async () => {
              let imageId: string | undefined;
              if (content.image?.src) {
                // The compressed picture goes up as a file (the request body), not as text inside the message.
                const file = dataUrlToBlob(content.image.src);
                const uploaded = await request(`/api/images?fileName=${encodeURIComponent(content.image.file)}`, {
                  method: "POST",
                  body: file,
                  headers: { "Content-Type": file.type },
                });
                imageId = (await uploaded.json()).id;
              }
              const response = await request(`/api/spaces/${spaceId}/messages`, {
                method: "POST",
                body: json({ text: content.text === undefined ? undefined : plain(content.text), imageId }),
              });
              let saved = parseMessage((await response.json()) as RawMessage);
              // Keep showing the local picture: loading the same one again from the server would make it flicker.
              if (saved.type === "message" && saved.image && content.image?.src) saved = { ...saved, image: { ...saved.image, src: content.image.src } };
              set((s) => ({ messages: { ...s.messages, [spaceId]: (s.messages[spaceId] ?? []).map((m) => (m.id === shown.id ? saved : m)) } }));
            },
          );
          return true;
        },

        createTaskFromMessage: (spaceId, text) => {
          const cardId = crypto.randomUUID();
          commit(
            (s) => {
              const input: CardInput = { title: text, details: "", priority: "medium", dueDate: null, labelIds: [], memberIds: [s.currentUserId] };
              return {
                cards: { ...s.cards, [cardId]: { ...input, id: cardId, progress: 0 } },
                columns: s.columns.map((c) => (c.id === "todo" ? { ...c, cardIds: [...c.cardIds, cardId] } : c)),
                messages: pushMessage(s.messages, spaceId, { ...stamp(s), type: "task", cardId }),
              };
            },
            send(`/api/spaces/${spaceId}/tasks`, "POST", { text, cardId }),
          );
          return cardId;
        },

        renameColumn: (id, name) =>
          commit(
            (s) => ({ columns: s.columns.map((c) => (c.id === id ? { ...c, name: name.trim() || undefined } : c)) }),
            send(`/api/columns/${id}`, "PATCH", { name: name.trim() }),
          ),

        setWipLimit: (id, limit) =>
          commit(
            (s) => ({ columns: s.columns.map((c) => (c.id === id ? { ...c, wipLimit: limit } : c)) }),
            send(`/api/columns/${id}`, "PATCH", { wipLimit: limit }),
          ),

        toggleColumn: (id) => {
          const collapsed = !get().columns.find((c) => c.id === id)!.collapsed;
          commit(
            (s) => ({ columns: s.columns.map((c) => (c.id === id ? { ...c, collapsed } : c)) }),
            send(`/api/columns/${id}`, "PATCH", { collapsed }),
          );
        },

        setLanguage: (language) => {
          // Before the board is there (the sign-in page) this is only a local choice, saved after sign-in.
          if (get().boardStatus !== "ready") return set({ language, languageChosenEarly: true });
          commit({ language }, send("/api/settings", "PATCH", { language }));
        },

        setDensity: (density) => commit({ density }, send("/api/settings", "PATCH", { density })),

        setView: (view) => {
          set({ view });
          if (view === "chat") readSpace(get().activeSpace);
        },

        openSpace: (spaceId) => {
          set({ activeSpace: spaceId });
          readSpace(spaceId);
        },

        openRoom: (cardId) => {
          set({ view: "chat", activeSpace: cardId });
          readSpace(cardId);
        },

        openDialog: (dialog) => set({ dialog }),

        closeDialog: () => set({ dialog: null }),

        dismissNotice: () => set({ notice: null }),

        loadBoard: async () => {
          const mine = epoch;
          set({ boardStatus: "loading" });
          try {
            const board = parseBoard((await (await request("/api/board")).json()) as RawBoard);
            if (mine !== epoch) return; // signed out while loading
            const chosen = get().language;
            const early = get().languageChosenEarly;
            applyBoard(early ? { ...board, language: chosen } : board);
            set({ boardStatus: "ready", languageChosenEarly: false });
            if (early && chosen !== board.language) enqueue({ snapshot: takeSnapshot(get()), send: send("/api/settings", "PATCH", { language: chosen }), epoch });
          } catch (error) {
            if (mine === epoch && !(error instanceof ApiError && error.status === 401)) set({ boardStatus: "error" });
          }
        },

        refresh: async () => {
          const mine = epoch;
          try {
            const board = parseBoard((await (await request("/api/board")).json()) as RawBoard);
            // Only when nothing newer is on its way, so the screen is never overwritten with older data.
            if (mine === epoch && !running && queue.length === 0) applyBoard(board);
          } catch {
            // Unreachable: the screen already shows the state from before the failed change.
          }
        },

        reset: () => {
          epoch += 1;
          queue = [];
          const { language: _keep, ...data } = emptyData(); // the language stays: the sign-in page uses it
          set({ ...data, dialog: null, lastDeleted: null, notice: null, boardStatus: "idle", languageChosenEarly: false, activeSpace: GENERAL_SPACE });
        },
      };
    },
    {
      name: "tidy-ui",
      version: 1,
      storage: lightStorage,
      partialize: ({ view, activeSpace, language }) => ({ view, activeSpace, language }),
    },
  ),
);
