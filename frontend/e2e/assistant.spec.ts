import { randomUUID } from "node:crypto";
import type { Page, Route } from "@playwright/test";
import { button, card, column, expect, setFa, settled, test } from "./helpers";

/**
 * The AI assistant panel. The AI routes are mocked (page.route); everything else is the real server.
 * What the mock "changes" is only what it puts in the board it returns, which is what the panel must show.
 */

interface Board {
  cards: Record<string, { id: string; title: unknown }>;
  columns: { id: string; cardIds: string[] }[];
  [key: string]: unknown;
}

const getBoard = async (page: Page): Promise<Board> => (await page.request.get("/api/board")).json();
const titleOf = (c: { title: unknown }) => (typeof c.title === "string" ? c.title : (c.title as { en: string }).en);

/** The board with one new card at the end of a column, as the server would return it after the assistant made it. */
async function withNewCard(page: Page, title: string, columnId = "todo") {
  const board = await getBoard(page);
  const id = randomUUID();
  board.cards[id] = { id, title, details: "", priority: "medium", dueDate: null, labelIds: [], memberIds: [], progress: 0 } as Board["cards"][string];
  board.columns.find((c) => c.id === columnId)!.cardIds.push(id);
  return { board, id };
}

async function withMovedCard(page: Page, title: string, to: string) {
  const board = await getBoard(page);
  const id = Object.values(board.cards).find((c) => titleOf(c) === title)!.id;
  for (const c of board.columns) c.cardIds = c.cardIds.filter((x) => x !== id);
  board.columns.find((c) => c.id === to)!.cardIds.push(id);
  return { board, id };
}

interface Mock {
  chats: { message: string }[];
  boardRequests: string[];
}

async function mockAi(page: Page, { history = [] as unknown[], configured = true, chat }: { history?: unknown[]; configured?: boolean; chat?: (route: Route, call: number) => Promise<void> | void } = {}): Promise<Mock> {
  const mock: Mock = { chats: [], boardRequests: [] };
  page.on("request", (r) => r.url().endsWith("/api/board") && mock.boardRequests.push(r.method()));
  await page.route("**/api/ai/history", (route) => route.fulfill({ json: history }));
  await page.route("**/api/ai/status", (route) => route.fulfill({ json: { configured } }));
  await page.route("**/api/ai/chat", async (route) => {
    mock.chats.push(route.request().postDataJSON());
    await (chat ?? ((r: Route) => r.fulfill({ json: { reply: "OK.", applied: [], problem: null, board: {} } })))(route, mock.chats.length);
  });
  return mock;
}

const reply = (route: Route, body: { reply: string; applied?: unknown[]; board: unknown }, delay = 0) =>
  new Promise<void>((resolve) =>
    setTimeout(async () => {
      await route.fulfill({ json: { applied: [], problem: null, ...body } });
      resolve();
    }, delay),
  );

const fail = (route: Route, status: number, en: string, fa: string) => route.fulfill({ status, json: { detail: { en, fa } } });

const panel = (page: Page) => page.getByTestId("ai-panel");
const openPanel = async (page: Page) => {
  await button(page, /AI assistant|دستیار هوش مصنوعی/).click();
  await expect(panel(page)).toBeVisible();
};
const input = (page: Page) => panel(page).getByRole("textbox");
const allowFailedRequests = (errors: string[]) => errors.splice(0, errors.length, ...errors.filter((e) => !/Failed to load resource|net::ERR/.test(e)));

// ---- placement -----------------------------------------------------------------------------------------

test("opens at the inline-end side with the board still visible beside it, and its own item in the sidebar", async ({ page }) => {
  await mockAi(page);
  const item = button(page, "AI assistant");
  await expect(item).toBeVisible();
  await expect(item).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("button", { name: /^Chat/ })).toBeVisible(); // a separate item

  await item.click();
  await expect(panel(page)).toBeVisible();
  await expect(item).toHaveAttribute("aria-expanded", "true");
  const box = (await panel(page).boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(Math.round(box.x + box.width)).toBe(viewport.width); // at the end side
  expect(Math.round(box.width)).toBe(400);

  const firstCard = (await page.getByTestId("card").first().boundingBox())!;
  expect(firstCard.x + firstCard.width).toBeLessThanOrEqual(box.x); // the board is beside it, not under it
  await expect(page.getByRole("button", { name: /^Project board/ })).toHaveAttribute("aria-current", "page"); // still on the board
  await expect(page.getByTestId("card")).toHaveCount(10);

  await item.click();
  await expect(panel(page)).toHaveCount(0);
});

test("opens and closes with the A key and with Escape", async ({ page }) => {
  await mockAi(page);
  await page.keyboard.press("a");
  await expect(panel(page)).toBeVisible();
  await expect(input(page)).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
  await expect(button(page, "AI assistant")).toBeFocused();
  await page.keyboard.press("a");
  await expect(panel(page)).toBeVisible();
  await button(page, "Close").click();
  await expect(panel(page)).toHaveCount(0);
});

test("fills the screen below 768px (390px wide) and still works", async ({ page }) => {
  const { board, id } = await withNewCard(page, "Written on a phone");
  const mock = await mockAi(page, { chat: (route) => reply(route, { reply: "Done on a small screen.", applied: [{ type: "create_card", cardId: id, title: "Written on a phone", column: "todo" }], board }) });
  await page.setViewportSize({ width: 390, height: 800 });
  await openPanel(page);
  const box = (await panel(page).boundingBox())!;
  expect([Math.round(box.x), Math.round(box.y), Math.round(box.width), Math.round(box.height)]).toEqual([0, 0, 390, 800]);
  await expect(page.getByTestId("ai-example")).toHaveCount(3);
  for (const example of await page.getByTestId("ai-example").all()) expect((await example.boundingBox())!.x + (await example.boundingBox())!.width).toBeLessThanOrEqual(390); // nothing runs off the side

  await input(page).fill("Add a card");
  await input(page).press("Enter");
  await expect(page.getByTestId("ai-answer")).toContainText("Done on a small screen.");
  expect(mock.chats).toEqual([{ message: "Add a card" }]);
  await expect(page.getByTestId("ai-chip")).toHaveText("Created: Written on a phone");

  await button(page, "Close").click();
  await expect(panel(page)).toHaveCount(0);
});

// ---- empty state, history -------------------------------------------------------------------------------

test("an empty conversation shows a short guide with three examples; clicking one sends it", async ({ page }) => {
  const mock = await mockAi(page, { chat: (route) => reply(route, { reply: "Those cards are overdue: …", board: {} }, 600) });
  await openPanel(page);
  await expect(page.getByTestId("ai-guide")).toBeVisible();
  await expect(page.getByTestId("ai-example")).toHaveText(['Create a card "Write the release notes" in To do', 'Move "Column unit tests" to Review', "Which cards are overdue?"]);

  await page.getByTestId("ai-example").nth(2).click();
  expect(mock.chats).toEqual([{ message: "Which cards are overdue?" }]);
  await expect(page.getByTestId("ai-user-message")).toHaveText("Which cards are overdue?");
  await expect(page.getByTestId("ai-answer")).toContainText("Those cards are overdue");
  await expect(page.getByTestId("ai-guide")).toHaveCount(0);
});

test("the history is loaded from the server when the panel opens, with the changes of each answer as chips", async ({ page }) => {
  const board = await getBoard(page);
  const drag = Object.values(board.cards).find((c) => titleOf(c) === "Drag and drop cards")!.id;
  const history = [
    { id: 1, role: "user", content: "Move the drag card to Review", changes: null, createdAt: "2026-11-15T08:00:00.000Z" },
    { id: 2, role: "assistant", content: "I moved it.", changes: { applied: [{ type: "move_card", cardId: drag, column: "review" }], problem: null }, createdAt: "2026-11-15T08:00:05.000Z" },
  ];
  const asked: string[] = [];
  page.on("request", (r) => r.url().includes("/api/ai/history") && asked.push(r.url()));
  await mockAi(page, { history });
  await openPanel(page);
  await expect(page.getByTestId("ai-user-message")).toHaveText("Move the drag card to Review");
  await expect(page.getByTestId("ai-answer")).toContainText("I moved it.");
  await expect(page.getByTestId("ai-chip")).toHaveText("Moved: Drag and drop cards → Review");
  await expect(page.getByTestId("ai-guide")).toHaveCount(0);
  expect(asked).toHaveLength(1);
});

// ---- asking and the board update ------------------------------------------------------------------------

test("sending with Enter: 'thinking', a disabled input, then the answer; the board updates at once with no refetch and the new card flashes", async ({ page }) => {
  const { board, id } = await withNewCard(page, "Write the release notes");
  const mock = await mockAi(page, {
    chat: (route) => reply(route, { reply: "I created the card.", applied: [{ type: "create_card", cardId: id, title: "Write the release notes", column: "todo" }], board }, 900),
  });
  await openPanel(page);
  await input(page).fill("Create a card Write the release notes");
  await input(page).press("Enter");

  await expect(page.getByTestId("ai-thinking")).toBeVisible();
  await expect(input(page)).toBeDisabled();
  await expect(page.getByTestId("ai-user-message")).toHaveText("Create a card Write the release notes");
  await expect(card(column(page, "todo"), "Write the release notes")).toHaveCount(0); // nothing on the board before the answer

  const requestsBefore = mock.boardRequests.length;
  await expect(page.getByTestId("ai-answer")).toContainText("I created the card.");
  await expect(page.getByTestId("ai-thinking")).toHaveCount(0);
  await expect(input(page)).toBeEnabled();
  await expect(input(page)).toBeFocused();

  const created = card(column(page, "todo"), "Write the release notes");
  await expect(created).toBeVisible(); // straight from the answer
  await expect(created).toHaveAttribute("data-ai-changed", "true"); // flashing
  await expect(page.getByTestId("ai-chip")).toHaveText("Created: Write the release notes");
  await expect(page.getByTestId("board-count")).toHaveText("11");
  expect(mock.boardRequests.length).toBe(requestsBefore); // no refetch
  await expect(created).not.toHaveAttribute("data-ai-changed", /.*/, { timeout: 5000 }); // the flash is only for a moment
});

test("a moved card flashes in its new column, and the chip says where it went", async ({ page }) => {
  const { board, id } = await withMovedCard(page, "Column unit tests", "review");
  await mockAi(page, { chat: (route) => reply(route, { reply: "Moved.", applied: [{ type: "move_card", cardId: id, column: "review" }], board }) });
  await openPanel(page);
  await page.getByTestId("ai-example").nth(1).click();
  await expect(card(column(page, "review"), "Column unit tests")).toBeVisible();
  await expect(card(column(page, "review"), "Column unit tests")).toHaveAttribute("data-ai-changed", "true");
  await expect(card(column(page, "todo"), "Column unit tests")).toHaveCount(0);
  await expect(page.getByTestId("ai-chip")).toHaveText("Moved: Column unit tests → Review");
});

test("clicking a chip opens that card", async ({ page }) => {
  const { board, id } = await withNewCard(page, "Open me from the chip");
  await mockAi(page, { chat: (route) => reply(route, { reply: "Made it.", applied: [{ type: "create_card", cardId: id, title: "Open me from the chip", column: "todo" }], board }) });
  await openPanel(page);
  await input(page).fill("make a card");
  await input(page).press("Enter");
  await page.getByTestId("ai-chip").click();
  const dialog = page.getByRole("dialog", { name: "Edit card" });
  await expect(dialog.getByLabel("Title")).toHaveValue("Open me from the chip");
  await page.keyboard.press("Escape");
  await expect(panel(page)).toBeVisible(); // the panel stays
});

test("an answer without changes leaves the board alone", async ({ page }) => {
  const mock = await mockAi(page, { chat: (route) => reply(route, { reply: "Three cards are in progress.", board: { cards: {}, columns: [] } }) });
  await openPanel(page);
  await input(page).fill("How many are in progress?");
  await input(page).press("Enter");
  await expect(page.getByTestId("ai-answer")).toContainText("Three cards are in progress.");
  await expect(page.getByTestId("card")).toHaveCount(10);
  await expect(page.getByTestId("ai-changes")).toHaveCount(0);
  expect(mock.chats).toHaveLength(1);
});

// ---- errors ----------------------------------------------------------------------------------------------

const errors = [
  { name: "service busy (429/503)", fail: (route: Route) => fail(route, 503, "The AI assistant is busy right now.", "دستیار مشغول است"), text: "The AI assistant is busy right now. Nothing was changed.", fa: "دستیار هوش مصنوعی اکنون مشغول است" },
  { name: "service failure", fail: (route: Route) => fail(route, 502, "The AI assistant could not answer.", "نتوانست پاسخ دهد"), text: "The AI assistant could not answer (the service reported a problem).", fa: "دستیار هوش مصنوعی نتوانست پاسخ دهد" },
  { name: "AI not configured (answered by the server)", fail: (route: Route) => fail(route, 503, "AI is not configured", "هوش مصنوعی پیکربندی نشده است"), text: "AI is not configured. Add OPENROUTER_API_KEY to the .env file and restart Tidy.", fa: "هوش مصنوعی پیکربندی نشده است" },
  { name: "a connection that drops (and a timeout)", fail: (route: Route) => route.abort("connectionreset"), text: "Can't reach the server. Nothing was changed.", fa: "ارتباط با سرور برقرار نشد" },
];

for (const language of ["en", "fa"] as const) {
  for (const e of errors) {
    test(`${e.name}: a clear message in ${language === "en" ? "English" : "Persian"} with Try again, and the rest of the app keeps working`, async ({ page, errors: consoleErrors }) => {
      let failing = true;
      const mock = await mockAi(page, {
        chat: async (route) => {
          if (failing) return e.fail(route);
          const { board, id } = await withNewCard(page, "Second try");
          return reply(route, { reply: "It worked this time.", applied: [{ type: "create_card", cardId: id, title: "Second try", column: "todo" }], board });
        },
      });
      if (language === "fa") {
        await setFa(page);
        await settled(page);
      }
      await openPanel(page);
      await input(page).fill(language === "fa" ? "یک کارت بساز" : "make a card");
      await input(page).press("Enter");

      const alert = page.getByTestId("ai-error");
      await expect(alert).toContainText(language === "fa" ? e.fa : e.text);
      await expect(alert.getByRole("button", { name: language === "fa" ? "تلاش دوباره" : "Try again" })).toBeVisible();
      await expect(page.getByTestId("ai-thinking")).toHaveCount(0);
      await expect(page.getByTestId("ai-answer")).toHaveCount(0);

      // The board and the team chat are untouched and still work: move a card with the keyboard.
      await expect(page.getByTestId("card")).toHaveCount(10);
      const target = language === "fa" ? "تست‌های واحد ستون‌ها" : "Column unit tests";
      await card(page, target).getByRole("button").first().focus();
      await page.keyboard.press(language === "fa" ? "," : ".");
      await expect(card(column(page, language === "fa" ? "ideas" : "doing"), target)).toBeVisible();

      failing = false;
      await alert.getByRole("button").click();
      await expect(page.getByTestId("ai-answer")).toContainText("It worked this time.");
      await expect(alert).toHaveCount(0);
      expect(mock.chats).toHaveLength(2);
      expect(mock.chats[1]).toEqual(mock.chats[0]); // the same question, sent again
      await expect(page.getByTestId("ai-user-message")).toHaveCount(1); // not shown twice
      allowFailedRequests(consoleErrors);
    });
  }
}

test("'not configured' is shown when the panel opens, the input is disabled, and Try again checks again", async ({ page }) => {
  let configured = false;
  await mockAi(page, { configured });
  await page.route("**/api/ai/status", (route) => route.fulfill({ json: { configured } }));
  await openPanel(page);
  const alert = page.getByTestId("ai-error");
  await expect(alert).toContainText("AI is not configured. Add OPENROUTER_API_KEY");
  await expect(input(page)).toBeDisabled();
  await expect(page.getByTestId("card")).toHaveCount(10); // the board works
  configured = true;
  await alert.getByRole("button", { name: "Try again" }).click();
  await expect(alert).toHaveCount(0);
  await expect(input(page)).toBeEnabled();
});

// ---- Persian and right-to-left ---------------------------------------------------------------------------

test("in Persian the panel is on the left, reads right-to-left, and the examples, answer and chips are in Persian", async ({ page }) => {
  await setFa(page);
  await settled(page);
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  // The mocked answer carries the board as the server has it now, which already says Persian.
  const { board, id } = await withNewCard(page, "یادداشت انتشار");
  const mock = await mockAi(page, { chat: (route) => reply(route, { reply: "کارت ساخته شد.", applied: [{ type: "create_card", cardId: id, title: "یادداشت انتشار", column: "todo" }], board }) });
  await openPanel(page);

  const box = (await panel(page).boundingBox())!;
  expect(Math.round(box.x)).toBe(0); // the end side is the left
  expect(Math.round(box.width)).toBe(400);
  const sidebar = (await page.getByRole("complementary", { name: "نوار کناری" }).boundingBox())!;
  expect(sidebar.x).toBeGreaterThan(box.x + box.width); // the sidebar is on the right
  const firstCard = (await page.getByTestId("card").first().boundingBox())!;
  expect(firstCard.x).toBeGreaterThanOrEqual(box.x + box.width); // the board is beside the panel

  await expect(page.getByRole("heading", { level: 2, name: "دستیار هوش مصنوعی" })).toBeVisible();
  await expect(page.getByTestId("ai-example")).toHaveCount(3);
  await expect(page.getByTestId("ai-example").first()).toContainText("یک کارت «نوشتن یادداشت انتشار»");
  await expect(input(page)).toHaveAttribute("dir", "auto");

  await page.getByTestId("ai-example").first().click();
  expect(mock.chats[0].message).toContain("نوشتن یادداشت انتشار");
  await expect(page.getByTestId("ai-user-message").locator("p")).toHaveAttribute("dir", "auto");
  await expect(page.getByTestId("ai-answer").locator("p")).toHaveAttribute("dir", "auto");
  await expect(page.getByTestId("ai-answer")).toContainText("کارت ساخته شد.");
  await expect(page.getByTestId("ai-chip")).toHaveText("ساخته شد: یادداشت انتشار");
  await expect(card(column(page, "todo"), "یادداشت انتشار")).toBeVisible();
});

test("English text in a Persian page and Persian text in an English page both keep their own direction", async ({ page }) => {
  await mockAi(page, { chat: (route) => reply(route, { reply: "بله، انجام شد.", board: {} }) });
  await openPanel(page);
  await input(page).fill("یک کارت بساز");
  await input(page).press("Enter");
  const answer = page.getByTestId("ai-answer").locator("p");
  await expect(answer).toHaveText("بله، انجام شد.");
  expect(await answer.evaluate((el) => getComputedStyle(el).direction)).toBe("rtl"); // Persian text in an LTR page
});
