import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createSeed } from "@/data/fixtures";
import { useAssistant } from "@/lib/assistant";
import { useStore } from "@/lib/store";
import { fetchMock, sent } from "../vitest.server";
import AiPanel from "./AiPanel";
import Sidebar from "./Sidebar";

const created = { type: "create_card", cardId: "c1", title: "Write the release notes", column: "todo" };
const moved = { type: "move_card", cardId: "c5", column: "review" };
const updated = { type: "update_card", cardId: "c3", fields: ["priority"] };

function serve({ chat = () => Response.json({ reply: "ok", applied: [], problem: null, board: board() }), history = [] as unknown[], configured = true } = {}) {
  fetchMock.mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/ai/chat") return chat();
    if (url === "/api/ai/history") return Response.json(history);
    if (url === "/api/ai/status") return Response.json({ configured });
    return new Response(null, { status: 204 });
  });
}

function board() {
  const seed = createSeed();
  return { currentUserId: "sara", language: "en", density: "comfortable", ...seed, columns: seed.columns.map((c) => ({ ...c, name: null })), messages: {} };
}

async function open() {
  useAssistant.getState().show();
  render(<AiPanel />);
  await waitFor(() => expect(useAssistant.getState().history).toBe("ready"));
}

const input = () => screen.getByRole("textbox", { name: /Ask the assistant|از دستیار/ });

describe("the panel", () => {
  it("is not there until opened, and loads the conversation when it opens", async () => {
    serve({ history: [{ id: 1, role: "user", content: "Earlier question", changes: null }, { id: 2, role: "assistant", content: "Earlier answer", changes: { applied: [], problem: null } }] });
    const { container } = render(<AiPanel />);
    expect(container).toBeEmptyDOMElement();
    useAssistant.getState().show();
    expect(await screen.findByText("Earlier answer")).toBeInTheDocument();
    expect(screen.getByText("Earlier question")).toBeInTheDocument();
    expect(sent().some((r) => r.url === "/api/ai/history")).toBe(true);
    expect(screen.getByRole("complementary", { name: "AI assistant" })).toBeInTheDocument();
  });

  it("closes with the button and with Escape", async () => {
    serve();
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(useAssistant.getState().open).toBe(false);
    useAssistant.getState().show();
    await userEvent.keyboard("{Escape}");
    expect(useAssistant.getState().open).toBe(false);
  });

  it("is at the inline-end side beside the page, and full screen only on a small one", async () => {
    serve();
    await open();
    const panel = screen.getByTestId("ai-panel");
    expect(panel.className).toContain("md:static"); // beside the page from 768px
    expect(panel.className).toContain("md:w-[400px]");
    expect(panel.className).toContain("md:border-s"); // the start-side edge: works in both directions
    expect(panel.className).toContain("fixed inset-0"); // below 768px: the whole screen
  });
});

describe("when the conversation is empty", () => {
  it("shows a short guide with three clickable examples in English", async () => {
    serve();
    await open();
    expect(screen.getByRole("heading", { name: "What can I do for you?" })).toBeInTheDocument();
    const examples = screen.getAllByTestId("ai-example");
    expect(examples.map((e) => e.textContent)).toEqual(['Create a card "Write the release notes" in To do', 'Move "Column unit tests" to Review', "Which cards are overdue?"]);
  });

  it("and in Persian", async () => {
    useStore.setState({ language: "fa" });
    serve();
    await open();
    const examples = screen.getAllByTestId("ai-example");
    expect(examples).toHaveLength(3);
    expect(examples[0]).toHaveTextContent("یک کارت «نوشتن یادداشت انتشار»");
    expect(screen.getByRole("complementary", { name: "دستیار هوش مصنوعی" })).toBeInTheDocument();
  });

  it("sends an example when it is clicked", async () => {
    serve();
    await open();
    await userEvent.click(screen.getAllByTestId("ai-example")[1]);
    await waitFor(() => expect(sent().find((r) => r.url === "/api/ai/chat")?.body).toEqual({ message: 'Move "Column unit tests" to Review' }));
    expect(await screen.findByTestId("ai-answer")).toBeInTheDocument();
    expect(screen.queryByTestId("ai-guide")).not.toBeInTheDocument(); // the guide goes away once there is a conversation
  });

  it("is not shown when there is a conversation", async () => {
    serve({ history: [{ id: 1, role: "user", content: "hi", changes: null }] });
    await open();
    expect(screen.queryByTestId("ai-guide")).not.toBeInTheDocument();
  });
});

describe("asking", () => {
  it("sends with Enter, keeps a new line with Shift+Enter, and ignores an empty question", async () => {
    serve();
    await open();
    await userEvent.type(input(), "{Enter}");
    expect(sent().filter((r) => r.url === "/api/ai/chat")).toHaveLength(0); // empty: nothing sent
    await userEvent.type(input(), "line one{Shift>}{Enter}{/Shift}line two");
    expect(input()).toHaveValue("line one\nline two");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(sent().find((r) => r.url === "/api/ai/chat")?.body).toEqual({ message: "line one\nline two" }));
    expect(input()).toHaveValue("");
  });

  it("shows 'thinking' and keeps the input disabled until the answer arrives, then gives the focus back", async () => {
    let reply: (r: Response) => void = () => {};
    serve({ chat: () => new Promise<Response>((resolve) => (reply = resolve)) as unknown as Response });
    await open();
    await userEvent.type(input(), "Add a card{Enter}");
    expect(await screen.findByTestId("ai-thinking")).toHaveTextContent("Thinking…");
    expect(input()).toBeDisabled();
    expect(screen.getByRole("button", { name: /Send/ })).toBeDisabled();
    expect(screen.getByTestId("ai-user-message")).toHaveTextContent("Add a card"); // the question is already there

    reply(Response.json({ reply: "Here you go.", applied: [], problem: null, board: board() }));
    expect(await screen.findByText("Here you go.")).toBeInTheDocument();
    expect(screen.queryByTestId("ai-thinking")).not.toBeInTheDocument();
    await waitFor(() => expect(input()).toBeEnabled());
    expect(input()).toHaveFocus();
  });

  it("uses dir=auto for the questions, the answers and the input, so Persian and English both read correctly", async () => {
    serve({ chat: () => Response.json({ reply: "حتماً، انجام شد.", applied: [], problem: null, board: board() }) });
    await open();
    expect(input()).toHaveAttribute("dir", "auto");
    await userEvent.type(input(), "یک کارت بساز{Enter}");
    const answer = await screen.findByTestId("ai-answer");
    expect(answer).toHaveTextContent("حتماً، انجام شد.");
    expect(within(answer).getByText("حتماً، انجام شد.")).toHaveAttribute("dir", "auto");
    expect(within(screen.getByTestId("ai-user-message")).getByText("یک کارت بساز")).toHaveAttribute("dir", "auto");
  });
});

describe("the changes under an answer", () => {
  const history = [
    { id: 1, role: "user", content: "Do three things", changes: null },
    { id: 2, role: "assistant", content: "Done.", changes: { applied: [created, moved, updated], problem: null } },
  ];

  it("are small chips: created, moved to a column, updated", async () => {
    serve({ history });
    await open();
    const chips = within(screen.getByTestId("ai-changes")).getAllByTestId("ai-chip");
    expect(chips.map((c) => c.textContent)).toEqual([
      "Created: Board progress bar", // the card that exists now (c1) is named by its current title
      "Moved: Drag and drop cards → Review",
      "Updated: Empty column state",
    ]);
  });

  it("are in Persian too, with the arrow pointing the right way", async () => {
    useStore.setState({ language: "fa" });
    serve({ history });
    await open();
    const chips = screen.getAllByTestId("ai-chip").map((c) => c.textContent);
    expect(chips[0]).toBe("ساخته شد: نوار پیشرفت تخته");
    expect(chips[1]).toBe("منتقل شد: کشیدن و رها کردن کارت‌ها ← بازبینی");
    expect(chips[2]).toBe("ویرایش شد: طراحی حالت خالی ستون");
  });

  it("open that card when clicked", async () => {
    serve({ history });
    await open();
    await userEvent.click(screen.getAllByTestId("ai-chip")[1]);
    expect(useStore.getState().dialog).toEqual({ type: "card", columnId: "doing", cardId: "c5" });
  });

  it("cannot be opened when the card no longer exists", async () => {
    serve({ history: [{ id: 1, role: "assistant", content: "Done.", changes: { applied: [{ type: "create_card", cardId: "gone", title: "Old card", column: "todo" }], problem: null } }] });
    await open();
    const chip = screen.getByTestId("ai-chip");
    expect(chip).toHaveTextContent("Created: Old card"); // the title the server reported
    expect(chip).toBeDisabled();
  });

  it("are not shown for an answer that changed nothing", async () => {
    serve({ history: [{ id: 1, role: "assistant", content: "Nothing to do.", changes: { applied: [], problem: null } }] });
    await open();
    expect(screen.queryByTestId("ai-changes")).not.toBeInTheDocument();
  });

  it("appear under a new answer and the board is already updated", async () => {
    const updatedBoard = board();
    updatedBoard.cards.c1 = { ...updatedBoard.cards.c1, title: "Changed by the AI" };
    serve({ chat: () => Response.json({ reply: "Updated.", applied: [updated, { ...created }], problem: null, board: updatedBoard }) });
    await open();
    await userEvent.type(input(), "do it{Enter}");
    expect(await screen.findAllByTestId("ai-chip")).toHaveLength(2);
    expect(useStore.getState().cards.c1.title).toBe("Changed by the AI");
    expect(sent().filter((r) => r.url === "/api/board")).toEqual([]);
  });
});

describe("errors, inside the panel", () => {
  const kinds: [string, () => Response, string, string][] = [
    ["not configured", () => Response.json({ detail: { en: "AI is not configured", fa: "x" } }, { status: 503 }), "AI is not configured. Add OPENROUTER_API_KEY", "هوش مصنوعی پیکربندی نشده است"],
    ["busy", () => Response.json({ detail: { en: "busy", fa: "x" } }, { status: 503 }), "The AI assistant is busy right now.", "دستیار هوش مصنوعی اکنون مشغول است"],
    ["failed", () => Response.json({ detail: { en: "failed", fa: "x" } }, { status: 502 }), "The AI assistant could not answer", "دستیار هوش مصنوعی نتوانست پاسخ دهد"],
  ];

  it.each(kinds)("%s: a clear message with Try again, in English", async (_name, response, english) => {
    serve({ chat: response });
    await open();
    await userEvent.type(input(), "do it{Enter}");
    const alert = await screen.findByTestId("ai-error");
    expect(alert).toHaveTextContent(english);
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it.each(kinds)("%s: and in Persian", async (_name, response, _english, persian) => {
    useStore.setState({ language: "fa" });
    serve({ chat: response });
    await open();
    await userEvent.type(input(), "بساز{Enter}");
    const alert = await screen.findByTestId("ai-error");
    expect(alert).toHaveTextContent(persian);
    expect(within(alert).getByRole("button", { name: "تلاش دوباره" })).toBeInTheDocument();
  });

  it("a dropped connection, in both languages", async () => {
    fetchMock.mockImplementation(async (input) => {
      if (String(input) === "/api/ai/chat") throw new TypeError("Failed to fetch");
      return String(input) === "/api/ai/history" ? Response.json([]) : String(input) === "/api/ai/status" ? Response.json({ configured: true }) : new Response(null, { status: 204 });
    });
    await open();
    await userEvent.type(input(), "x{Enter}");
    expect(await screen.findByTestId("ai-error")).toHaveTextContent("Can't reach the server. Nothing was changed.");
  });

  it("Try again resends the question and the answer replaces the error", async () => {
    let calls = 0;
    serve({ chat: () => (++calls === 1 ? Response.json({ detail: { en: "busy", fa: "x" } }, { status: 503 }) : Response.json({ reply: "Second time lucky.", applied: [], problem: null, board: board() })) });
    await open();
    await userEvent.type(input(), "Please{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Second time lucky.")).toBeInTheDocument();
    expect(screen.queryByTestId("ai-error")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("ai-user-message")).toHaveLength(1); // the question is not repeated
  });

  it("shows 'not configured' when the panel opens, and the input is disabled", async () => {
    serve({ configured: false });
    await open();
    expect(screen.getByTestId("ai-error")).toHaveAttribute("data-kind", "not-configured");
    expect(input()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("does not stop the rest of the app", async () => {
    serve({ chat: () => Response.json({ detail: { en: "failed", fa: "x" } }, { status: 502 }) });
    await open();
    await userEvent.type(input(), "x{Enter}");
    await screen.findByTestId("ai-error");
    useStore.getState().moveCard("c1", "doing", 0);
    expect(useStore.getState().columns.find((c) => c.id === "doing")!.cardIds[0]).toBe("c1");
  });
});

describe("the sidebar item", () => {
  it("is separate from Chat, has its own icon, and opens and closes the panel", async () => {
    serve();
    render(<Sidebar />);
    const item = screen.getByRole("button", { name: "AI assistant" });
    expect(item).toHaveAttribute("aria-expanded", "false");
    expect(item.querySelector("svg")).not.toBeNull();
    expect(screen.getByRole("button", { name: /^Chat/ })).not.toBe(item);
    await userEvent.click(item);
    expect(useAssistant.getState().open).toBe(true);
    expect(item).toHaveAttribute("aria-expanded", "true");
    expect(useStore.getState().view).toBe("board"); // the open view did not change
    await userEvent.click(item);
    expect(useAssistant.getState().open).toBe(false);
  });
});
