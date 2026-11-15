import type { Page } from "@playwright/test";
import { boardNav, button, card, column, composer, createUser, expect, login, makeImage, openRoom, plainTest, reload, setFa, settled, test, type TestUser } from "./helpers";

/**
 * Every kind of change, made through the real screen: card (new, moved with the keyboard, edited, deleted),
 * column name, WIP limit, collapse, progress, assignees, message, image, task from a message, unread,
 * density and language. Then the same data must come back after a refresh, after signing out and in,
 * in a brand-new browser, and (two-phase test at the end) after the container restarts.
 */
async function applyAllChanges(page: Page) {
  // New card
  await button(page, "Add card to Ideas").click();
  const dialog = page.getByRole("dialog", { name: "New card" });
  await dialog.getByLabel("Title").fill("E2E new card");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(card(column(page, "ideas"), "E2E new card")).toBeVisible();

  // Move with the keyboard: To do -> In progress
  await card(page, "Column unit tests").getByRole("button", { name: "Column unit tests" }).focus();
  await page.keyboard.press(".");
  await expect(card(column(page, "doing"), "Column unit tests")).toBeVisible();

  // Column name, WIP limit, collapse
  const ideas = column(page, "ideas");
  await button(ideas, "Ideas column menu").click();
  await ideas.getByRole("menuitem", { name: "Rename column" }).click();
  await ideas.getByRole("textbox").fill("Backlog");
  await ideas.getByRole("textbox").press("Enter");
  await expect(ideas.getByRole("heading")).toHaveText("Backlog");
  const todo = column(page, "todo");
  await button(todo, "To do column menu").click();
  await todo.getByRole("menuitem", { name: /Set WIP limit/ }).click();
  await todo.getByRole("spinbutton").fill("5");
  await todo.getByRole("spinbutton").press("Enter");
  await expect(todo.getByTestId("wip-count")).toHaveText("1 / 5");
  const review = column(page, "review");
  await button(review, "Review column menu").click();
  await review.getByRole("menuitem", { name: "Collapse column" }).click();
  await expect(review).toHaveAttribute("data-collapsed", "true");

  // Delete a card with the keyboard
  await card(page, "Keyboard shortcut sheet").getByRole("button", { name: "Keyboard shortcut sheet" }).focus();
  await page.keyboard.press("Delete");
  await expect(card(page, "Keyboard shortcut sheet")).toHaveCount(0);

  // Progress, posted to the room, and an assignee
  await openRoom(page, "Jalali date picker");
  await page.getByRole("slider", { name: "Progress" }).fill("70");
  await button(page, "Post progress update").click();
  await expect(page.getByTestId("event").filter({ hasText: /70/ })).toHaveCount(1);
  await button(page, "+ Reza Mohammadi").click();
  await expect(page.getByTestId("panel-member")).toHaveCount(2);

  // Edit a card from its panel
  await boardNav(page).click();
  await openRoom(page, "Board progress bar");
  await button(page, "Edit task").click();
  const edit = page.getByRole("dialog", { name: "Edit card" });
  await button(edit, "High").click();
  await edit.getByLabel("Title").fill("E2E edited title");
  await edit.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "E2E edited title" })).toBeVisible();

  // Chat: a message, an image, a task from a message (this also reads General)
  await button(page, "General").click();
  await composer(page).fill("Hello e2e");
  await composer(page).press("Enter");
  await expect(page.getByText("Hello e2e")).toBeVisible();
  const buffer = await makeImage(page, { width: 10, height: 10 });
  await page.getByLabel("Attach image").setInputFiles({ name: "e2e-picture.png", mimeType: "image/png", buffer });
  await expect(page.getByRole("img", { name: "e2e-picture.png" })).toBeVisible();
  await composer(page).fill("Task from e2e");
  await button(page, "Create task").click();
  await expect(page.getByTestId("task-created").filter({ hasText: "Task from e2e" })).toBeVisible();
  await expect(page.getByTestId("unread-badge")).toHaveText("1"); // only the task chat room is still unread
  await page.getByTestId("room").filter({ hasText: "Task chat room" }).click();
  await expect(page.getByTestId("unread-badge")).toHaveCount(0);

  // Density, then language (last: everything after it is in Persian)
  await boardNav(page).click();
  await button(page, "Compact").click();
  await expect(button(page, "Compact")).toHaveAttribute("aria-pressed", "true");
  await setFa(page);
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await settled(page);
}

/** The page may open on any view (the last open view is a light preference in the browser): go to the board first. */
async function expectAllChanges(page: Page) {
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.keyboard.press("g");
  await page.keyboard.press("b");

  // Language and density come from the server
  expect(await (await page.request.get("/api/settings")).json()).toEqual({ language: "fa", density: "compact" });
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");

  // Cards
  await expect(card(column(page, "ideas"), "E2E new card")).toBeVisible();
  await expect(card(column(page, "ideas"), "E2E edited title")).toBeVisible();
  await expect(card(page, "نوار پیشرفت تخته")).toHaveCount(0); // the edited card has its new title, not the sample one
  await expect(card(column(page, "doing"), "تست‌های واحد ستون‌ها")).toBeVisible(); // moved
  await expect(card(page, "راهنمای میانبرها")).toHaveCount(0); // deleted
  await expect(page.getByTestId("board-count")).toHaveText(/^(11|۱۱)$/); // 10 + new + task from a message - deleted

  // Columns
  await expect(column(page, "ideas").getByRole("heading")).toHaveText("Backlog");
  await expect(column(page, "todo").getByTestId("wip-count")).toHaveText(/[5۵]$/);
  await expect(column(page, "review")).toHaveAttribute("data-collapsed", "true");

  // Details only the server can confirm
  const board = await (await page.request.get("/api/board")).json();
  const edited = Object.values<{ title: unknown; priority: string }>(board.cards).find((c) => c.title === "E2E edited title")!;
  expect(edited.priority).toBe("high");

  // Progress, its event and the assignee
  await page.getByTestId("room").filter({ hasText: "انتخابگر تاریخ شمسی" }).click();
  await expect(page.getByTestId("panel-progress")).toHaveText(/70|۷۰/);
  await expect(page.getByTestId("event").filter({ hasText: /70|۷۰/ })).toHaveCount(1);
  await expect(page.getByTestId("panel-member")).toHaveCount(2);

  // General: message, image, task announcement; nothing unread
  await page.getByTestId("sidebar-scroll").getByRole("button").first().click();
  await expect(page.getByText("Hello e2e")).toBeVisible();
  await expect(page.getByRole("img", { name: "e2e-picture.png" })).toHaveJSProperty("naturalWidth", 10);
  await expect(page.getByTestId("task-created").filter({ hasText: "Task from e2e" })).toBeVisible();
  await expect(page.getByTestId("unread-badge")).toHaveCount(0);
}

async function signOutThenInAgain(page: Page, user: TestUser) {
  await page.getByTestId("profile").locator("button[aria-haspopup=menu]").click();
  await page.getByRole("menuitem").click();
  await expect(page.locator('input[name="username"]')).toBeVisible(); // the sign-in page, whatever the language
  await expect(page.getByTestId("card")).toHaveCount(0);
  await page.locator('input[name="username"]').fill(user.username);
  await page.locator('input[name="password"]').fill(user.password);
  await page.locator("button[type=submit]").click();
  await expect(page.getByTestId("card").first()).toBeVisible();
}

test("every kind of change is still there after a refresh", async ({ page }) => {
  await applyAllChanges(page);
  await reload(page);
  await expectAllChanges(page);
});

test("every kind of change is still there after signing out and in again", async ({ page, user }) => {
  await applyAllChanges(page);
  await settled(page);
  await signOutThenInAgain(page, user);
  await expectAllChanges(page);
});

test("every kind of change is there in a brand-new browser: it lives on the server, not in this one", async ({ page, browser, user }, testInfo) => {
  await applyAllChanges(page);
  await settled(page);
  const fresh = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
  try {
    const other = await fresh.newPage();
    await login(other, user);
    await other.goto("/");
    await expect(other.getByTestId("card").first()).toBeVisible();
    await expectAllChanges(other);
  } finally {
    await fresh.close();
  }
});

// ---- across a container restart: run twice, with the restart in between (see frontend/AGENTS.md) ----
//   PERSIST_PHASE=write  PERSIST_USER=restart-check npx playwright test e2e/persistence.spec.ts -g "container restart"
//   docker restart (or scripts\stop + start)
//   PERSIST_PHASE=verify PERSIST_USER=restart-check npx playwright test e2e/persistence.spec.ts -g "container restart"

plainTest("across a container restart (two phases)", async ({ page, request }) => {
  const phase = process.env.PERSIST_PHASE;
  const username = process.env.PERSIST_USER ?? "restart-check";
  plainTest.skip(!phase, "set PERSIST_PHASE=write or verify, with a container restart in between");
  const user: TestUser = { username, password: "password" };

  if (phase === "write") {
    await createUser(request, username);
    await login(page, user);
    await page.goto("/");
    await expect(page.getByTestId("card").first()).toBeVisible();
    await applyAllChanges(page);
    await settled(page);
  } else {
    await login(page, user); // the same user, after the restart
    await page.goto("/");
    await expect(page.getByTestId("card").first()).toBeVisible();
    await expectAllChanges(page);
  }
});
