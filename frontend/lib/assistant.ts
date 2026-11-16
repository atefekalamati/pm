import { create } from "zustand";
import { api, json, request, type RawBoard } from "./api";
import { useStore, whenIdle } from "./store";

/** A change the assistant made, as the server reports it. */
export interface AiChange {
  type: "create_card" | "update_card" | "move_card";
  cardId: string;
  title?: string;
  column?: string;
  fields?: string[];
}

export interface AiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  changes: AiChange[];
}

/** not-configured: no API key. busy: 429/503 after one retry. failed: the service failed. timeout: no answer in time. offline: our server cannot be reached. */
export type AiErrorKind = "not-configured" | "busy" | "failed" | "timeout" | "offline";

export interface AiError {
  kind: AiErrorKind;
  /** The question to send again with "Try again"; null when there is nothing to resend (the panel reloads instead). */
  retry: string | null;
}

/** The backend waits up to about two minutes on a busy service (60 s, a retry after 2 s, 60 s): wait a little longer. */
export const CHAT_TIMEOUT_MS = 130_000;
export const HIGHLIGHT_MS = 2200;

interface AssistantState {
  open: boolean;
  history: "idle" | "loading" | "ready";
  messages: AiMessage[];
  waiting: boolean;
  error: AiError | null;
  /** Cards the assistant just changed: they flash for a moment. */
  highlight: string[];
  show: () => void;
  hide: () => void;
  toggle: () => void;
  loadHistory: () => Promise<void>;
  send: (text: string) => Promise<void>;
  retry: () => Promise<void>;
  reset: () => void;
}

interface HistoryRow {
  id: number;
  role: "user" | "assistant";
  content: string;
  changes: { applied?: AiChange[] } | null;
}

interface ChatAnswer {
  reply: string;
  applied: AiChange[];
  board: RawBoard;
}

let highlightTimer: ReturnType<typeof setTimeout> | undefined;
let epoch = 0; // bumped on sign-out, so an answer for the last user never reaches the next one

function classify(status: number, body: { detail?: { en?: string } | string } | null): AiErrorKind {
  const english = typeof body?.detail === "object" ? body.detail.en : undefined;
  if (status === 503 && english === "AI is not configured") return "not-configured";
  return status === 503 ? "busy" : "failed";
}

const initial = () => ({ open: false, history: "idle" as const, messages: [] as AiMessage[], waiting: false, error: null as AiError | null, highlight: [] as string[] });

export const useAssistant = create<AssistantState>()((set, get) => {
  async function ask(text: string, alreadyShown: boolean) {
    if (get().waiting) return;
    const mine = epoch;
    const user: AiMessage = { id: crypto.randomUUID(), role: "user", content: text, changes: [] };
    set((s) => ({ waiting: true, error: null, messages: alreadyShown ? s.messages : [...s.messages, user] }));
    const fail = (kind: AiErrorKind) => mine === epoch && set({ waiting: false, error: { kind, retry: text } });

    try {
      await whenIdle(); // the server must have everything the user changed before the assistant looks at the board
      const response = await api("/api/ai/chat", { method: "POST", body: json({ message: text }), signal: AbortSignal.timeout(CHAT_TIMEOUT_MS) });
      if (mine !== epoch) return;
      if (response.status === 401) return; // the session ended: lib/api sent the user to sign-in
      if (!response.ok) return void fail(classify(response.status, await response.json().catch(() => null)));

      const answer = (await response.json()) as ChatAnswer;
      if (mine !== epoch) return;
      set((s) => ({ waiting: false, messages: [...s.messages, { id: crypto.randomUUID(), role: "assistant", content: answer.reply, changes: answer.applied }] }));
      if (answer.applied.length) {
        useStore.getState().applyServerBoard(answer.board); // straight into the screen, no second request
        flash([...new Set(answer.applied.map((change) => change.cardId))]);
      }
    } catch (error) {
      fail(error instanceof DOMException && (error.name === "TimeoutError" || error.name === "AbortError") ? "timeout" : "offline");
    }
  }

  function flash(ids: string[]) {
    clearTimeout(highlightTimer);
    set({ highlight: ids });
    highlightTimer = setTimeout(() => set({ highlight: [] }), HIGHLIGHT_MS);
  }

  return {
    ...initial(),
    show: () => set({ open: true }),
    hide: () => set({ open: false }),
    toggle: () => set((s) => ({ open: !s.open })),

    loadHistory: async () => {
      if (get().waiting) return; // an answer is on its way: do not replace the conversation under it
      const mine = epoch;
      set({ history: "loading", error: null });
      try {
        const [rows, status] = await Promise.all([
          request("/api/ai/history").then((r) => r.json() as Promise<HistoryRow[]>),
          request("/api/ai/status").then((r) => r.json() as Promise<{ configured: boolean }>),
        ]);
        if (mine !== epoch || get().waiting) return;
        set({
          history: "ready",
          messages: rows.map((row) => ({ id: String(row.id), role: row.role, content: row.content, changes: row.changes?.applied ?? [] })),
          error: status.configured ? null : { kind: "not-configured", retry: null },
        });
      } catch {
        if (mine === epoch) set({ history: "ready", error: { kind: "offline", retry: null } });
      }
    },

    send: (text) => ask(text.trim(), false),
    retry: () => {
      const { error } = get();
      return error?.retry ? ask(error.retry, true) : get().loadHistory();
    },

    reset: () => {
      epoch += 1;
      clearTimeout(highlightTimer);
      set(initial());
    },
  };
});
