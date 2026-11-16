import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parseBoard, parseMessage, type RawBoard } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { Message } from "@/lib/types";
import Conversation from "./Conversation";

const event = (id: string, rest: object, byAi = true) => ({ id, type: "event", authorId: "sara", time: "10:00", byAi, ...rest }) as Message;

function showRoom(messages: Message[]) {
  useStore.setState({ messages: { ...useStore.getState().messages, c3: messages } });
  render(<Conversation spaceId="c3" />);
  // The space before the dot is drawn by the layout (a flex gap), not part of the text.
  return screen.getAllByTestId("event").map((row) => (row.textContent ?? "").replace(/\s*·\s*/, " · "));
}

describe("events made by the AI assistant", () => {
  it("name the assistant, not the user, in English", () => {
    const rows = showRoom([
      event("1", { event: "created" }),
      event("2", { event: "updated" }),
      event("3", { event: "moved", columnId: "review" }),
      event("4", { event: "added", memberId: "ali" }),
      event("5", { event: "removed", memberId: "ali" }),
      event("6", { event: "progress", value: 50 }),
    ]);
    expect(rows).toEqual([
      "AI assistant created this card · 10:00",
      "AI assistant updated this card · 10:00",
      "AI assistant moved this to Review · 10:00",
      "AI assistant added Ali Rezaei · 10:00",
      "AI assistant removed Ali Rezaei · 10:00",
      "AI assistant set progress to 50% · 10:00",
    ]);
  });

  it("name the assistant in Persian", () => {
    useStore.setState({ language: "fa" });
    const rows = showRoom([event("1", { event: "created" }), event("2", { event: "updated" }), event("3", { event: "moved", columnId: "review" })]);
    expect(rows[0]).toContain("دستیار هوش مصنوعی این کارت را ساخت");
    expect(rows[1]).toContain("دستیار هوش مصنوعی این کارت را ویرایش کرد");
    expect(rows[2]).toContain("دستیار هوش مصنوعی این کار را منتقل کرد");
  });

  it("do not change how the user's own events read", () => {
    const rows = showRoom([event("1", { event: "moved", columnId: "review" }, false), event("2", { event: "updated" }, false)]);
    expect(rows).toEqual(["You moved this to Review · 10:00", "You updated this card · 10:00"]);
  });
});

describe("the server's by_ai flag", () => {
  it("is kept when a message is converted for the screen", () => {
    const message = parseMessage({ id: "9", type: "event", authorId: "u", createdAt: "2026-11-15T08:30:00.000Z", event: "moved", columnId: "doing", byAi: true });
    expect(message).toMatchObject({ type: "event", event: "moved", byAi: true });
    expect(message).not.toHaveProperty("createdAt");
  });

  it("survives a whole board", () => {
    const raw = {
      currentUserId: "u", language: "en", density: "comfortable", columns: [], cards: {}, members: {}, unread: {},
      messages: { c1: [{ id: "1", type: "event", authorId: "u", createdAt: "2026-11-15T08:30:00.000Z", event: "created", byAi: true }] },
    } as unknown as RawBoard;
    expect(parseBoard(raw).messages.c1[0]).toMatchObject({ event: "created", byAi: true });
  });
});
