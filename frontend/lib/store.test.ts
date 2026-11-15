import { describe, expect, it, vi } from "vitest";
import { GENERAL_SPACE } from "@/data/constants";
import { createSeed } from "@/data/fixtures";
import { failRequests, fetchMock, sent } from "../vitest.server";
import { ApiError } from "./api";
import { initialState, placeCard, useStore, whenIdle } from "./store";
import type { CardInput } from "./types";

const store = () => useStore.getState();
const column = (id: string) => store().columns.find((c) => c.id === id)!;
const lastMessage = (space: string) => store().messages[space].at(-1)!;

const input: CardInput = {
  title: "New",
  details: "",
  priority: "low",
  dueDate: null,
  labelIds: [],
  memberIds: ["ali"],
};

describe("cards", () => {
  it("adds a card at the end of a column with zero progress", () => {
    const id = store().addCard("review", input);
    expect(column("review").cardIds.at(-1)).toBe(id);
    expect(store().cards[id]).toMatchObject({ title: "New", progress: 0, memberIds: ["ali"] });
  });

  it("updates a card without touching its progress", () => {
    store().updateCard("c5", { ...input, title: "Edited" });
    expect(store().cards.c5).toMatchObject({ title: "Edited", progress: 60 });
  });

  it("deletes a card with its room, unread count and task announcements", () => {
    store().openSpace("c7");
    store().deleteCard("c7");
    expect(store().cards.c7).toBeUndefined();
    expect(column("doing").cardIds).not.toContain("c7");
    expect(store().messages.c7).toBeUndefined();
    expect(store().unread.c7).toBeUndefined();
    expect(store().messages.general.some((m) => m.type === "task" && m.cardId === "c7")).toBe(false);
    expect(store().activeSpace).toBe(GENERAL_SPACE);
  });
});

describe("undo delete", () => {
  const snapshot = () =>
    structuredClone({
      cards: store().cards,
      cardOrder: Object.keys(store().cards),
      columns: store().columns,
      messages: store().messages,
      unread: store().unread,
    });

  it("restores everything exactly as it was", () => {
    store().setProgress("c7", 70);
    store().removeMember("c7", "reza");
    const before = snapshot();
    store().deleteCard("c7");
    expect(store().lastDeleted?.card.id).toBe("c7");
    expect(snapshot()).not.toEqual(before);
    store().undoDelete();
    expect(snapshot()).toEqual(before);
    expect(store().lastDeleted).toBeNull();
  });

  it("restores the column position of a card in the middle", () => {
    store().deleteCard("c6");
    expect(column("doing").cardIds).toEqual(["c5", "c7"]);
    store().undoDelete();
    expect(column("doing").cardIds).toEqual(["c5", "c6", "c7"]);
  });

  it("restores the task announcement at its place in General", () => {
    const before = store().messages.general.map((m) => m.id);
    store().deleteCard("c7");
    store().undoDelete();
    expect(store().messages.general.map((m) => m.id)).toEqual(before);
  });

  it("keeps messages sent after the delete", () => {
    store().deleteCard("c7");
    store().sendMessage("general", { text: "later" });
    store().undoDelete();
    expect(store().messages.general.at(-1)).toMatchObject({ text: "later" });
    expect(store().messages.general.some((m) => m.type === "task" && m.cardId === "c7")).toBe(true);
  });

  it("reopens the room if it was the active space", () => {
    store().openSpace("c7");
    store().deleteCard("c7");
    expect(store().activeSpace).toBe(GENERAL_SPACE);
    store().undoDelete();
    expect(store().activeSpace).toBe("c7");
  });

  it("restores a card that had no conversation", () => {
    store().deleteCard("c1");
    store().undoDelete();
    expect(store().cards.c1).toBeDefined();
    expect(store().messages.c1).toBeUndefined();
  });

  it("does nothing after the undo window is dismissed", () => {
    store().deleteCard("c1");
    store().dismissUndo();
    store().undoDelete();
    expect(store().cards.c1).toBeUndefined();
  });

  it("undoes the most recent delete", () => {
    store().deleteCard("c1");
    store().deleteCard("c2");
    store().undoDelete();
    expect(store().cards.c2).toBeDefined();
    expect(store().cards.c1).toBeUndefined();
  });

});

describe("moveCard", () => {
  it("reorders within a column without logging an event", () => {
    const before = store().messages.c1;
    store().moveCard("c2", "ideas", 0);
    expect(column("ideas").cardIds).toEqual(["c2", "c1"]);
    expect(store().messages.c1).toBe(before);
    expect(store().messages.c2).toBeUndefined();
  });

  it("moves across columns and logs one room event", () => {
    store().moveCard("c1", "doing", 1);
    expect(column("ideas").cardIds).toEqual(["c2"]);
    expect(column("doing").cardIds).toEqual(["c5", "c1", "c6", "c7"]);
    expect(store().messages.c1).toHaveLength(1);
    expect(lastMessage("c1")).toMatchObject({ type: "event", event: "moved", columnId: "doing", authorId: "sara" });
  });

  it("is never blocked by a WIP limit", () => {
    store().moveCard("c1", "doing", 0);
    expect(column("doing").cardIds).toHaveLength(4);
    expect(column("doing").wipLimit).toBe(3);
  });

  it("moves to the end of the adjacent column and stops at the edges", () => {
    store().moveCardBy("c4", 1);
    expect(column("doing").cardIds.at(-1)).toBe("c4");
    store().moveCardBy("c4", -1);
    expect(column("todo").cardIds.at(-1)).toBe("c4");
    store().moveCardBy("c9", 1);
    expect(column("done").cardIds).toContain("c9");
    store().moveCardBy("c1", -1);
    expect(column("ideas").cardIds).toContain("c1");
  });

  it("placeCard does not change the input", () => {
    const columns = store().columns;
    const copy = JSON.stringify(columns);
    placeCard(columns, "c1", "done", 0);
    expect(JSON.stringify(columns)).toBe(copy);
  });
});

describe("progress and members", () => {
  it("sets progress without an event and posts one on request", () => {
    const count = store().messages.c5.length;
    store().setProgress("c5", 75);
    expect(store().cards.c5.progress).toBe(75);
    expect(store().messages.c5).toHaveLength(count);
    store().postProgress("c5");
    expect(lastMessage("c5")).toMatchObject({ event: "progress", value: 75 });
  });

  it("posts 100 for a card in Done", () => {
    store().setProgress("c9", 40);
    store().postProgress("c9");
    expect(lastMessage("c9")).toMatchObject({ event: "progress", value: 100 });
  });

  it("adds and removes members with events", () => {
    store().addMember("c1", "reza");
    expect(store().cards.c1.memberIds).toEqual(["maryam", "reza"]);
    expect(lastMessage("c1")).toMatchObject({ event: "added", memberId: "reza" });
    store().removeMember("c1", "maryam");
    expect(store().cards.c1.memberIds).toEqual(["reza"]);
    expect(lastMessage("c1")).toMatchObject({ event: "removed", memberId: "maryam" });
  });
});

describe("chat", () => {
  it("sends a message as the current user", () => {
    expect(store().sendMessage("c1", { text: "hello" })).toBe(true);
    expect(lastMessage("c1")).toMatchObject({ type: "message", authorId: "sara", text: "hello" });
    expect(lastMessage("c1").time).toMatch(/^\d\d:\d\d$/);
  });

  it("turns a message into a To do card and announces it", () => {
    const id = store().createTaskFromMessage("general", "Write docs");
    expect(column("todo").cardIds.at(-1)).toBe(id);
    expect(store().cards[id]).toMatchObject({ title: "Write docs", priority: "medium", memberIds: ["sara"], progress: 0, dueDate: null });
    expect(lastMessage("general")).toMatchObject({ type: "task", cardId: id });
  });

  it("clears unread counts as spaces are opened", () => {
    expect(store().unread).toEqual({ general: 2, c7: 1 });
    store().setView("chat");
    expect(store().unread).toEqual({ c7: 1 });
    store().openRoom("c7");
    expect(store().unread).toEqual({});
    expect(store()).toMatchObject({ view: "chat", activeSpace: "c7" });
  });
});

describe("columns and preferences", () => {
  it("renames a column and restores the default when blank", () => {
    store().renameColumn("todo", "  Next  ");
    expect(column("todo").name).toBe("Next");
    store().renameColumn("todo", "   ");
    expect(column("todo").name).toBeUndefined();
  });

  it("sets a WIP limit and collapses a column", () => {
    store().setWipLimit("todo", 5);
    expect(column("todo").wipLimit).toBe(5);
    store().toggleColumn("todo");
    expect(column("todo").collapsed).toBe(true);
  });

  it("changes language and density", () => {
    store().setLanguage("fa");
    store().setDensity("compact");
    expect(store()).toMatchObject({ language: "fa", density: "compact" });
  });
});

const DATA_URL = "data:image/png;base64,iVBORw0KGgo=";

describe("every change is shown at once and then sent", () => {
  const requests = () => sent().map((r) => `${r.method} ${r.url}`);

  it("sends a new card with the id it already shows", async () => {
    const id = store().addCard("todo", { ...input, title: "Mine", memberIds: ["sara"] });
    expect(store().cards[id].title).toBe("Mine"); // visible before any answer
    await whenIdle();
    expect(sent()).toEqual([
      expect.objectContaining({
        method: "POST",
        url: "/api/cards",
        body: { id, columnId: "todo", title: "Mine", details: "", priority: "low", dueDate: null, labelIds: [], memberIds: ["sara"] },
      }),
    ]);
  });

  it("sends each kind of change to its own route", async () => {
    store().updateCard("c1", { ...input, title: "Edited", memberIds: [] });
    store().moveCard("c1", "doing", 0);
    store().setProgress("c1", 40);
    store().postProgress("c1");
    store().addMember("c1", "ali");
    store().removeMember("c1", "ali");
    store().renameColumn("todo", " Next ");
    store().setWipLimit("todo", 4);
    store().toggleColumn("todo");
    store().setLanguage("fa");
    store().setDensity("compact");
    store().deleteCard("c2");
    store().undoDelete();
    await whenIdle();
    expect(requests()).toEqual([
      "PATCH /api/cards/c1",
      "POST /api/cards/c1/move",
      "PATCH /api/cards/c1",
      "POST /api/cards/c1/post-progress",
      "POST /api/cards/c1/members",
      "DELETE /api/cards/c1/members/ali",
      "PATCH /api/columns/todo",
      "PATCH /api/columns/todo",
      "PATCH /api/columns/todo",
      "PATCH /api/settings",
      "PATCH /api/settings",
      "DELETE /api/cards/c2",
      "POST /api/cards/c2/restore",
    ]);
    const bodies = sent().map((r) => r.body);
    expect(bodies[1]).toEqual({ columnId: "doing", index: 0 });
    expect(bodies[6]).toEqual({ name: "Next" });
    expect(bodies[7]).toEqual({ wipLimit: 4 });
    expect(bodies[8]).toEqual({ collapsed: true });
    expect(bodies[9]).toEqual({ language: "fa" });
    expect(bodies[10]).toEqual({ density: "compact" });
  });

  it("sends changes one at a time, in the order they were made", async () => {
    let inFlight = 0;
    let most = 0;
    const normal = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      most = Math.max(most, ++inFlight);
      await new Promise((resolve) => setTimeout(resolve, 5));
      inFlight -= 1;
      return normal(input, init);
    });
    const id = store().addCard("todo", input);
    store().moveCard(id, "doing", 0); // needs the card to exist on the server first
    store().updateCard(id, { ...input, title: "Later" });
    await whenIdle();
    expect(requests()).toEqual(["POST /api/cards", `POST /api/cards/${id}/move`, `PATCH /api/cards/${id}`]);
    expect(most).toBe(1);
  });

  it("merges a burst of progress changes into the latest value", async () => {
    for (const value of [10, 20, 30, 40, 50]) store().setProgress("c1", value);
    expect(store().cards.c1.progress).toBe(50);
    await whenIdle();
    const progress = sent().map((r) => r.body);
    expect(progress.length).toBeLessThan(5);
    expect(progress.at(-1)).toEqual({ progress: 50 }); // the server ends with the last value
  });

  it("opens a conversation: the unread count goes at once, the server is told once", async () => {
    store().openRoom("c7");
    expect(store().unread).toEqual({ general: 2 });
    store().openRoom("c3"); // nothing unread there: nothing to send
    await whenIdle();
    expect(requests()).toEqual(["POST /api/spaces/c7/read"]);
  });

  it("sends a task made from a message with the card id it shows", async () => {
    const id = store().createTaskFromMessage("general", "Write docs");
    await whenIdle();
    expect(sent()[0]).toMatchObject({ method: "POST", url: "/api/spaces/general/tasks", body: { text: "Write docs", cardId: id } });
  });
});

describe("images go up as a file", () => {
  it("uploads the picture as the request body, then sends a message that only names it", async () => {
    store().sendMessage("general", { text: "look", image: { src: DATA_URL, file: "my photo.png" } });
    const shown = store().messages.general.at(-1)!;
    expect(shown).toMatchObject({ type: "message", text: "look", image: { src: DATA_URL, file: "my photo.png" } }); // visible at once
    await whenIdle();

    const [upload, message] = sent();
    expect(upload).toMatchObject({ method: "POST", url: "/api/images?fileName=my%20photo.png", contentType: "image/png" });
    expect(upload.body).toBeInstanceOf(Blob); // a file, not text
    expect((upload.body as Blob).size).toBeGreaterThan(0);
    expect(message.url).toBe("/api/spaces/general/messages");
    expect(JSON.stringify(message.body)).not.toContain("data:"); // no Data URL anywhere in the message
    expect(message.body).toEqual({ text: "look", imageId: expect.stringMatching(/^image-/) });

    const saved = store().messages.general.at(-1)!;
    expect(saved.id).toMatch(/^server-/); // the server's message replaced the one shown first
    expect(saved).toMatchObject({ text: "look", image: { file: "my photo.png", src: DATA_URL } }); // the same picture stays, no flicker
  });

  it("sends a text message without any upload", async () => {
    store().sendMessage("c1", { text: "hello" });
    await whenIdle();
    expect(sent().map((r) => r.url)).toEqual(["/api/spaces/c1/messages"]);
  });
});

describe("a change that fails is undone", () => {
  const board = () => {
    const { columns, cards, members, messages, unread, language, density } = store();
    return { columns, cards, members, messages, unread, language, density };
  };

  const kinds: [string, () => void, string][] = [
    ["a new card", () => store().addCard("todo", input), "/api/cards"],
    ["a card edit", () => store().updateCard("c1", { ...input, title: "Edited" }), "/api/cards/c1"],
    ["a move", () => store().moveCard("c1", "done", 0), "/move"],
    ["a delete", () => store().deleteCard("c1"), "/api/cards/c1"],
    ["progress", () => store().setProgress("c1", 80), "/api/cards/c1"],
    ["a progress post", () => store().postProgress("c1"), "/post-progress"],
    ["adding an assignee", () => store().addMember("c1", "ali"), "/members"],
    ["removing an assignee", () => store().removeMember("c5", "ali"), "/members/ali"],
    ["a column name", () => store().renameColumn("todo", "Renamed"), "/api/columns/todo"],
    ["a WIP limit", () => store().setWipLimit("todo", 3), "/api/columns/todo"],
    ["collapsing a column", () => store().toggleColumn("todo"), "/api/columns/todo"],
    ["a message", () => store().sendMessage("general", { text: "hi" }), "/messages"],
    ["an image", () => store().sendMessage("general", { image: { src: DATA_URL, file: "a.png" } }), "/api/images"],
    ["a task from a message", () => store().createTaskFromMessage("general", "Task"), "/tasks"],
    ["opening a conversation", () => store().openRoom("c7"), "/read"],
    ["the language", () => store().setLanguage("fa"), "/api/settings"],
    ["the density", () => store().setDensity("compact"), "/api/settings"],
  ];

  it.each(kinds)("puts everything back when the server refuses %s", async (_name, change, part) => {
    const before = board();
    failRequests(part, 500);
    change();
    expect(board()).not.toEqual(before); // it was shown at once
    await whenIdle();
    expect(board()).toEqual(before); // and then taken back
    expect(store().notice).not.toBeNull();
  });

  it.each(kinds)("puts everything back when the connection drops during %s", async (_name, change, part) => {
    const before = board();
    failRequests(part, "network");
    change();
    await whenIdle();
    expect(board()).toEqual(before);
    expect(store().notice).not.toBeNull();
  });

  it("closes the undo toast of a delete that failed", async () => {
    failRequests("/api/cards/c1", 500, "DELETE");
    store().deleteCard("c1");
    expect(store().lastDeleted).not.toBeNull();
    await whenIdle();
    expect(store().lastDeleted).toBeNull();
    expect(store().cards.c1).toBeDefined();
  });

  it("drops the changes queued behind a failed one, which were built on it", async () => {
    failRequests("/api/cards", 500, "POST");
    const id = store().addCard("todo", input);
    store().moveCard(id, "doing", 0);
    store().setProgress(id, 30);
    await whenIdle();
    expect(store().cards[id]).toBeUndefined();
    expect(sent().filter((r) => r.method !== "GET").map((r) => `${r.method} ${r.url}`)).toEqual(["POST /api/cards"]); // nothing else was sent
  });

  it("asks the server for the truth after a failure, and shows it", async () => {
    const real = createSeed();
    real.cards.c1 = { ...real.cards.c1, progress: 77 };
    fetchMock.mockImplementation(async (input) => {
      if (String(input) === "/api/board") {
        return Response.json({ currentUserId: "sara", language: "en", density: "comfortable", ...real, columns: real.columns.map((c) => ({ ...c, name: null })), messages: {} });
      }
      if (String(input).includes("/move")) return new Response(null, { status: 500 });
      return new Response(null, { status: 204 });
    });
    store().moveCard("c1", "done", 0);
    await whenIdle();
    await vi.waitFor(() => expect(store().cards.c1.progress).toBe(77)); // the board the server sent
    expect(store().notice).not.toBeNull();
  });

  it("does not undo anything for a 401: the session ended and the sign-in page takes over", async () => {
    failRequests("/api/cards/c1", 401, "PATCH");
    store().updateCard("c1", { ...input, title: "x" });
    await whenIdle();
    expect(store().notice).toBeNull();
  });

  it("numbers each failure so the toast shows again", async () => {
    failRequests("/api/settings", 500);
    store().setDensity("compact");
    await whenIdle();
    const first = store().notice;
    store().dismissNotice();
    store().setDensity("compact");
    await whenIdle();
    expect(store().notice).not.toBeNull();
    expect(store().notice).not.toBe(first);
    expect(new ApiError(500).status).toBe(500);
  });
});

describe("loading the board", () => {
  const server = (overrides: object = {}) => {
    const real = createSeed();
    return {
      currentUserId: "sara",
      language: "fa",
      density: "compact",
      ...real,
      columns: real.columns.map((c) => ({ ...c, name: c.id === "todo" ? "Next up" : null })),
      messages: { general: [{ id: "1", type: "message", authorId: "ali", createdAt: "2026-11-15T08:30:00.000Z", text: "Hello" }] },
      ...overrides,
    };
  };

  it("starts empty, so no sample data or empty board can flash", () => {
    const fresh = initialState();
    expect(fresh).toMatchObject({ boardStatus: "idle", columns: [], cards: {}, members: {}, messages: {}, unread: {}, currentUserId: "" });
  });

  it("takes everything from the server: columns, language, density, unread and message times", async () => {
    useStore.getState().reset();
    fetchMock.mockImplementation(async () => Response.json(server()));
    const loading = store().loadBoard();
    expect(store().boardStatus).toBe("loading");
    await loading;
    expect(store().boardStatus).toBe("ready");
    expect(column("todo").name).toBe("Next up");
    expect(column("ideas").name).toBeUndefined(); // null becomes "show the default"
    expect(store()).toMatchObject({ language: "fa", density: "compact", currentUserId: "sara", unread: { general: 2, c7: 1 } });
    const hello = store().messages.general[0];
    expect(hello).toMatchObject({ id: "1", type: "message", text: "Hello", authorId: "ali" });
    expect(hello.time).toMatch(/^\d\d:\d\d$/); // local HH:mm from the server's UTC time
    expect(hello).not.toHaveProperty("createdAt");
  });

  it("shows an error state when the server cannot be reached, and loads on retry", async () => {
    useStore.getState().reset();
    fetchMock.mockImplementation(async () => {
      throw new TypeError("Failed to fetch");
    });
    await store().loadBoard();
    expect(store().boardStatus).toBe("error");
    fetchMock.mockImplementation(async () => Response.json(server()));
    await store().loadBoard();
    expect(store().boardStatus).toBe("ready");
  });

  it("treats a server error the same as unreachable", async () => {
    useStore.getState().reset();
    fetchMock.mockImplementation(async () => new Response(null, { status: 500 }));
    await store().loadBoard();
    expect(store().boardStatus).toBe("error");
  });

  it("falls back to General when the saved open conversation is not on this board", async () => {
    useStore.getState().reset();
    useStore.setState({ view: "chat", activeSpace: "someone-elses-card" });
    fetchMock.mockImplementation(async () => Response.json(server()));
    await store().loadBoard();
    expect(store()).toMatchObject({ view: "chat", activeSpace: GENERAL_SPACE });
  });

  it("keeps a language chosen on the sign-in page and saves it", async () => {
    useStore.getState().reset();
    store().setLanguage("fa"); // before sign-in: local only
    expect(sent()).toEqual([]);
    fetchMock.mockImplementation(async (input) => (String(input) === "/api/board" ? Response.json(server({ language: "en" })) : new Response(null, { status: 204 })));
    await store().loadBoard();
    await whenIdle();
    expect(store().language).toBe("fa");
    expect(sent().at(-1)).toMatchObject({ method: "PATCH", url: "/api/settings", body: { language: "fa" } });
  });

  it("uses the server's language when none was chosen before sign-in", async () => {
    useStore.getState().reset();
    fetchMock.mockImplementation(async () => Response.json(server({ language: "fa" })));
    await store().loadBoard();
    expect(store().language).toBe("fa");
    expect(sent().filter((r) => r.method === "PATCH")).toEqual([]);
  });
});

describe("signing out", () => {
  it("forgets the user's board but keeps the language for the sign-in page", () => {
    store().setLanguage("fa");
    store().reset();
    expect(store()).toMatchObject({ boardStatus: "idle", columns: [], cards: {}, members: {}, messages: {}, unread: {}, currentUserId: "", language: "fa" });
  });

  it("ignores an answer that arrives after sign-out", async () => {
    let release: () => void = () => {};
    const normal = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      await new Promise<void>((resolve) => (release = resolve));
      throw new TypeError("late failure for " + String(input) + String(init?.method));
    });
    store().updateCard("c1", { ...input, title: "Mine" });
    store().reset(); // the next person signs in on this screen
    useStore.setState({ ...createSeed(), currentUserId: "sara", boardStatus: "ready" });
    release();
    await whenIdle();
    expect(store().notice).toBeNull(); // the old user's failure did not touch the new screen
    expect(store().cards.c1.title).toEqual(createSeed().cards.c1.title);
    fetchMock.mockImplementation(normal);
  });
});

describe("what stays in the browser", () => {
  const stored = () => JSON.parse(localStorage.getItem("tidy-ui")!).state;

  it("is only the open view, the open conversation and the language", () => {
    store().setView("chat");
    store().openSpace("c3");
    store().setLanguage("fa");
    store().addCard("todo", input);
    store().setDensity("compact");
    expect(Object.keys(stored()).sort()).toEqual(["activeSpace", "language", "view"]);
    expect(stored()).toEqual({ view: "chat", activeSpace: "c3", language: "fa" });
    expect(localStorage.length).toBe(1);
    expect(JSON.stringify(localStorage)).not.toContain("Write docs");
  });

  it("never saves cards, messages, unread counts, members, density or the undo snapshot", () => {
    store().deleteCard("c1");
    const raw = localStorage.getItem("tidy-ui")!;
    for (const word of ["cards", "messages", "unread", "members", "density", "lastDeleted", "Board progress bar"]) expect(raw).not.toContain(word);
  });

  it("has defaults of English, comfortable and Board", () => {
    expect(initialState()).toMatchObject({ language: "en", density: "comfortable", view: "board" });
  });
});
