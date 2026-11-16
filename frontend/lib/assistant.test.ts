import { describe, expect, it, vi } from "vitest";
import { createSeed } from "@/data/fixtures";
import { fetchMock, sent } from "../vitest.server";
import { onUnauthorized } from "./api";
import { CHAT_TIMEOUT_MS, HIGHLIGHT_MS, useAssistant } from "./assistant";
import { useStore, whenIdle } from "./store";

const ai = () => useAssistant.getState();
const store = () => useStore.getState();

/** The seed as the server sends a board, with the title of one card changed so a new board can be told apart. */
function boardAnswer(titleOfC1 = "Board progress bar") {
  const seed = createSeed();
  seed.cards.c1 = { ...seed.cards.c1, title: titleOfC1 };
  return { currentUserId: "sara", language: "en", density: "comfortable", ...seed, columns: seed.columns.map((c) => ({ ...c, name: null })), messages: {} };
}

const created = { type: "create_card", cardId: "c1", title: "Write the release notes", column: "todo" };

/** Answers the AI routes; anything else succeeds with nothing. */
function serve(chat: () => Response | Promise<Response>, { configured = true, history = [] as unknown[] } = {}) {
  fetchMock.mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/ai/chat") return chat();
    if (url === "/api/ai/history") return Response.json(history);
    if (url === "/api/ai/status") return Response.json({ configured });
    if (url === "/api/board") return Response.json(boardAnswer());
    return new Response(null, { status: 204 });
  });
}

const answer = (reply: string, applied: unknown[] = [], board = boardAnswer()) => Response.json({ reply, applied, problem: null, board });
const failure = (status: number, detail: unknown) => Response.json({ detail }, { status });
const chatCalls = () => sent().filter((r) => r.url === "/api/ai/chat");

describe("the panel", () => {
  it("opens, closes and toggles", () => {
    expect(ai().open).toBe(false);
    ai().show();
    expect(ai().open).toBe(true);
    ai().toggle();
    expect(ai().open).toBe(false);
    ai().toggle();
    ai().hide();
    expect(ai().open).toBe(false);
  });
});

describe("history", () => {
  it("is loaded from the server, with the changes of each answer", async () => {
    serve(() => answer("x"), {
      history: [
        { id: 1, role: "user", content: "Create it", changes: null },
        { id: 2, role: "assistant", content: "Done.", changes: { applied: [created], problem: null } },
        { id: 3, role: "assistant", content: "Nothing changed.", changes: { applied: [], problem: "bad" } },
      ],
    });
    await ai().loadHistory();
    expect(ai().history).toBe("ready");
    expect(ai().messages.map((m) => [m.role, m.content, m.changes.length])).toEqual([["user", "Create it", 0], ["assistant", "Done.", 1], ["assistant", "Nothing changed.", 0]]);
    expect(sent().map((r) => r.url).sort()).toEqual(["/api/ai/history", "/api/ai/status"]);
    expect(ai().error).toBeNull();
  });

  it("is empty for a new user", async () => {
    serve(() => answer("x"));
    await ai().loadHistory();
    expect(ai()).toMatchObject({ history: "ready", messages: [], error: null });
  });

  it("shows 'not configured' as soon as it is known", async () => {
    serve(() => answer("x"), { configured: false });
    await ai().loadHistory();
    expect(ai().error).toEqual({ kind: "not-configured", retry: null });
  });

  it("shows a connection error when the server cannot be reached, and loads again on retry", async () => {
    fetchMock.mockImplementation(async () => {
      throw new TypeError("Failed to fetch");
    });
    await ai().loadHistory();
    expect(ai().error).toEqual({ kind: "offline", retry: null });
    serve(() => answer("x"), { history: [{ id: 1, role: "user", content: "hi", changes: null }] });
    await ai().retry();
    expect(ai().error).toBeNull();
    expect(ai().messages).toHaveLength(1);
  });
});

describe("asking", () => {
  it("shows the question at once, waits, then adds the answer", async () => {
    let reply: (r: Response) => void = () => {};
    serve(() => new Promise<Response>((resolve) => (reply = resolve)));
    const done = ai().send("  How is it going?  ");
    expect(ai().waiting).toBe(true);
    expect(ai().messages.map((m) => [m.role, m.content])).toEqual([["user", "How is it going?"]]); // trimmed, and visible before the answer
    await vi.waitFor(() => expect(chatCalls()).toHaveLength(1));
    expect(chatCalls()[0]).toMatchObject({ method: "POST", body: { message: "How is it going?" } });

    reply(answer("All good."));
    await done;
    expect(ai().waiting).toBe(false);
    expect(ai().messages.map((m) => [m.role, m.content])).toEqual([["user", "How is it going?"], ["assistant", "All good."]]);
    expect(ai().error).toBeNull();
  });

  it("ignores a second question while one is waiting", async () => {
    let reply: (r: Response) => void = () => {};
    serve(() => new Promise<Response>((resolve) => (reply = resolve)));
    const first = ai().send("one");
    await ai().send("two"); // ignored
    await vi.waitFor(() => expect(chatCalls()).toHaveLength(1));
    reply(answer("ok"));
    await first;
    expect(ai().messages.filter((m) => m.role === "user").map((m) => m.content)).toEqual(["one"]);
  });

  it("puts the board of an answer with changes straight on screen, with no second request, and flashes the changed cards", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      serve(() => answer("Created it.", [created, { type: "move_card", cardId: "c2", column: "done" }], boardAnswer("Changed by the AI")));
      await ai().send("Make a card");
      expect(store().cards.c1.title).toBe("Changed by the AI");
      expect(sent().filter((r) => r.url === "/api/board")).toEqual([]); // not asked for again
      expect(ai().highlight).toEqual(["c1", "c2"]);
      expect(ai().messages.at(-1)!.changes).toEqual([created, { type: "move_card", cardId: "c2", column: "done" }]);
      vi.advanceTimersByTime(HIGHLIGHT_MS);
      expect(ai().highlight).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves the board alone when the answer changed nothing", async () => {
    serve(() => answer("Nothing to do.", [], boardAnswer("Should not show up")));
    const before = store().cards;
    await ai().send("What is on the board?");
    expect(store().cards).toBe(before);
    expect(ai().highlight).toEqual([]);
  });

  it("first lets the server have the user's own unsaved changes", async () => {
    const normal = fetchMock.getMockImplementation()!;
    let release: () => void = () => {};
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input) === "/api/settings") await new Promise<void>((resolve) => (release = resolve)); // a save that is slow
      return normal(input, init);
    });
    store().setDensity("compact"); // on its way
    const asked = ai().send("hello");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(chatCalls()).toHaveLength(0); // not yet: the save must finish first
    serve(() => answer("hi"));
    release();
    await asked;
    expect(chatCalls()).toHaveLength(1);
  });

  it("does not overwrite changes the user made while waiting: it fetches the board again once they are saved", async () => {
    let reply: (r: Response) => void = () => {};
    serve(() => new Promise<Response>((resolve) => (reply = resolve)));
    const asked = ai().send("Make a card");
    await vi.waitFor(() => expect(chatCalls()).toHaveLength(1));

    let finishSave: () => void = () => {};
    const normal = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input) === "/api/settings") await new Promise<void>((resolve) => (finishSave = resolve)); // a save that is slow
      return normal(input, init);
    });
    store().setDensity("compact"); // the user changes something while the assistant works; it is not saved yet
    reply(answer("Done.", [created], boardAnswer("From the AI")));
    await asked;
    expect(store().cards.c1.title).toEqual(createSeed().cards.c1.title); // the older board did not replace the screen
    expect(store().density).toBe("compact"); // and the user's change is still there
    expect(sent().filter((r) => r.url === "/api/board")).toEqual([]);

    finishSave(); // saved: now the board is fetched again, so the AI's changes appear too
    await whenIdle();
    await vi.waitFor(() => expect(store().cards.c1.title).toBe("Board progress bar"));
    expect(sent().filter((r) => r.url === "/api/board")).toHaveLength(1);
  });
});

describe("errors", () => {
  const cases: [string, () => Response, string][] = [
    ["not configured", () => failure(503, { en: "AI is not configured", fa: "هوش مصنوعی پیکربندی نشده است" }), "not-configured"],
    ["busy (429 or 503)", () => failure(503, { en: "busy", fa: "مشغول" }), "busy"],
    ["a service failure", () => failure(502, { en: "failed", fa: "ناموفق" }), "failed"],
    ["an unexpected status", () => failure(500, "oops"), "failed"],
  ];

  it.each(cases)("%s", async (_name, response, kind) => {
    serve(response);
    await ai().send("do something");
    expect(ai().waiting).toBe(false);
    expect(ai().error).toEqual({ kind, retry: "do something" });
    expect(ai().messages.map((m) => m.role)).toEqual(["user"]); // the question stays on screen; no answer
  });

  it("a connection that drops", async () => {
    fetchMock.mockImplementation(async () => {
      throw new TypeError("Failed to fetch");
    });
    await ai().send("x");
    expect(ai().error?.kind).toBe("offline");
  });

  it("no answer in time", async () => {
    fetchMock.mockImplementation(async () => {
      throw new DOMException("The operation timed out.", "TimeoutError");
    });
    await ai().send("x");
    expect(ai().error?.kind).toBe("timeout");
    expect(CHAT_TIMEOUT_MS).toBeGreaterThan(125_000); // longer than the server's own wait (two tries and a pause)
  });

  it("does not touch the board when it fails", async () => {
    const before = store().cards;
    serve(() => failure(502, { en: "x", fa: "y" }));
    await ai().send("x");
    expect(store().cards).toBe(before);
    expect(ai().highlight).toEqual([]);
  });

  it("Try again sends the same question once more, without showing it twice", async () => {
    let calls = 0;
    serve(() => (++calls === 1 ? failure(503, { en: "busy", fa: "مشغول" }) : answer("Now it worked.")));
    await ai().send("Please help");
    expect(ai().error?.kind).toBe("busy");
    await ai().retry();
    expect(ai().error).toBeNull();
    expect(ai().messages.map((m) => [m.role, m.content])).toEqual([["user", "Please help"], ["assistant", "Now it worked."]]);
    expect(chatCalls().map((c) => (c.body as { message: string }).message)).toEqual(["Please help", "Please help"]);
  });

  it("Try again after 'not configured' asks again (the key may have been added)", async () => {
    let configured = false;
    serve(() => (configured ? answer("Configured now.") : failure(503, { en: "AI is not configured", fa: "x" })));
    await ai().send("hi");
    expect(ai().error?.kind).toBe("not-configured");
    configured = true;
    await ai().retry();
    expect(ai().messages.at(-1)!.content).toBe("Configured now.");
  });

  it("the rest of the app keeps working after an error", async () => {
    serve(() => failure(502, { en: "x", fa: "y" }));
    await ai().send("x");
    store().moveCard("c1", "doing", 0);
    await whenIdle();
    expect(store().columns.find((c) => c.id === "doing")!.cardIds[0]).toBe("c1");
    expect(store().notice).toBeNull();
  });

  it("a 401 ends the session and shows no error here", async () => {
    const ended = vi.fn();
    onUnauthorized(ended);
    serve(() => new Response(null, { status: 401 }));
    await ai().send("x");
    expect(ended).toHaveBeenCalled();
    expect(ai().error).toBeNull();
    onUnauthorized(() => {});
  });
});

describe("signing out", () => {
  it("forgets the conversation, and a late answer never reaches the next user", async () => {
    let reply: (r: Response) => void = () => {};
    serve(() => new Promise<Response>((resolve) => (reply = resolve)));
    const asked = ai().send("secret question");
    await vi.waitFor(() => expect(chatCalls()).toHaveLength(1));
    ai().reset();
    expect(ai()).toMatchObject({ open: false, messages: [], waiting: false, error: null, highlight: [] });
    reply(answer("late answer", [created]));
    await asked;
    expect(ai().messages).toEqual([]);
    expect(ai().highlight).toEqual([]);
  });
});
