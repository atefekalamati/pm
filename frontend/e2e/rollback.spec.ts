import type { Page } from "@playwright/test";
import { boardNav, button, card, column, composer, expect, makeImage, openRoom, setFa, settled, test } from "./helpers";

/**
 * A change is shown at once and then sent. When the server refuses it (500) or the connection drops, the screen
 * goes back to how it was, a toast says so, and the server never saw the change. The failing server is a mock
 * (page.route) that answers after 700 ms, so the instant, optimistic state can be seen first.
 */

const TOAST_EN = "That change could not be saved, so it was undone.";
const TOAST_FA = "این تغییر ذخیره نشد و برگردانده شد.";
const toast = (page: Page) => page.getByTestId("notice-toast");

async function failing(page: Page, url: string | RegExp, method: string, how: "refuse" | "drop" = "refuse") {
  await page.route(url, async (route) => {
    if (route.request().method() !== method) return route.fallback();
    await new Promise((resolve) => setTimeout(resolve, 700));
    if (how === "drop") return route.abort("connectionreset");
    return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) });
  });
}

/** Failed requests are expected here; a real JavaScript error still fails the test. */
const allowFailedRequests = (errors: string[]) => errors.splice(0, errors.length, ...errors.filter((e) => !/Failed to load resource|net::ERR/.test(e)));

const serverBoard = async (page: Page) => (await page.request.get("/api/board")).json();

interface Kind {
  name: string;
  route: [string | RegExp, string];
  act: (page: Page) => Promise<void>;
  shown: (page: Page) => Promise<void>;
  undone: (page: Page) => Promise<void>;
  start?: (page: Page) => Promise<void>;
}

const inRoom = async (page: Page, title: string) => openRoom(page, title);

const kinds: Kind[] = [
  {
    name: "moving a card",
    route: [/\/api\/cards\/[^/]+\/move$/, "POST"],
    act: async (page) => {
      await card(page, "Column unit tests").getByRole("button", { name: "Column unit tests" }).focus();
      await page.keyboard.press(".");
    },
    shown: (page) => expect(card(column(page, "doing"), "Column unit tests")).toBeVisible(),
    undone: (page) => expect(card(column(page, "todo"), "Column unit tests")).toBeVisible(),
  },
  {
    name: "editing a card",
    route: [/\/api\/cards\/[^/]+$/, "PATCH"],
    start: (page) => inRoom(page, "Board progress bar"),
    act: async (page) => {
      await button(page, "Edit task").click();
      const dialog = page.getByRole("dialog", { name: "Edit card" });
      await dialog.getByLabel("Title").fill("Edited title");
      await dialog.getByRole("button", { name: "Save" }).click();
    },
    shown: (page) => expect(page.getByRole("heading", { level: 2, name: "Edited title" })).toBeVisible(),
    undone: (page) => expect(page.getByRole("heading", { level: 2, name: "Board progress bar" })).toBeVisible(),
  },
  {
    name: "deleting a card",
    route: [/\/api\/cards\/[^/]+$/, "DELETE"],
    act: async (page) => {
      await card(page, "Column unit tests").getByRole("button", { name: "Column unit tests" }).focus();
      await page.keyboard.press("Delete");
    },
    shown: (page) => expect(card(page, "Column unit tests")).toHaveCount(0),
    undone: async (page) => {
      await expect(card(page, "Column unit tests")).toHaveCount(1);
      await expect(page.getByTestId("undo-toast")).toHaveCount(0); // nothing left to undo
    },
  },
  {
    name: "renaming a column",
    route: [/\/api\/columns\/ideas$/, "PATCH"],
    act: async (page) => {
      const ideas = column(page, "ideas");
      await button(ideas, "Ideas column menu").click();
      await ideas.getByRole("menuitem", { name: "Rename column" }).click();
      await ideas.getByRole("textbox").fill("Backlog");
      await ideas.getByRole("textbox").press("Enter");
    },
    shown: (page) => expect(column(page, "ideas").getByRole("heading")).toHaveText("Backlog"),
    undone: (page) => expect(column(page, "ideas").getByRole("heading")).toHaveText("Ideas"),
  },
  {
    name: "setting a WIP limit",
    route: [/\/api\/columns\/todo$/, "PATCH"],
    act: async (page) => {
      const todo = column(page, "todo");
      await button(todo, "To do column menu").click();
      await todo.getByRole("menuitem", { name: /Set WIP limit/ }).click();
      await todo.getByRole("spinbutton").fill("2");
      await todo.getByRole("spinbutton").press("Enter");
    },
    shown: (page) => expect(column(page, "todo").getByTestId("wip-count")).toHaveText("2 / 2"),
    undone: (page) => expect(column(page, "todo").getByTestId("wip-count")).toHaveText("2"),
  },
  {
    name: "collapsing a column",
    route: [/\/api\/columns\/review$/, "PATCH"],
    act: async (page) => {
      const review = column(page, "review");
      await button(review, "Review column menu").click();
      await review.getByRole("menuitem", { name: "Collapse column" }).click();
    },
    shown: (page) => expect(column(page, "review")).toHaveAttribute("data-collapsed", "true"),
    undone: (page) => expect(column(page, "review")).not.toHaveAttribute("data-collapsed", "true"),
  },
  {
    name: "sending a message",
    route: [/\/api\/spaces\/general\/messages$/, "POST"],
    start: async (page) => {
      await page.getByRole("button", { name: /^Chat/ }).click();
    },
    act: async (page) => {
      await composer(page).fill("This will not be saved");
      await composer(page).press("Enter");
    },
    shown: (page) => expect(page.getByText("This will not be saved")).toBeVisible(),
    undone: (page) => expect(page.getByText("This will not be saved")).toHaveCount(0),
  },
  {
    name: "sending an image (the upload fails)",
    route: [/\/api\/images/, "POST"],
    start: async (page) => {
      await page.getByRole("button", { name: /^Chat/ }).click();
    },
    act: async (page) => {
      const buffer = await makeImage(page, { width: 10, height: 10 });
      await page.getByLabel("Attach image").setInputFiles({ name: "lost.png", mimeType: "image/png", buffer });
    },
    shown: (page) => expect(page.getByRole("img", { name: "lost.png" })).toBeVisible(),
    undone: (page) => expect(page.getByRole("img", { name: "lost.png" })).toHaveCount(0),
  },
  {
    name: "making a task from a message",
    route: [/\/api\/spaces\/general\/tasks$/, "POST"],
    start: async (page) => {
      await page.getByRole("button", { name: /^Chat/ }).click();
    },
    act: async (page) => {
      await composer(page).fill("A task that is refused");
      await button(page, "Create task").click();
    },
    shown: (page) => expect(page.getByTestId("task-created").filter({ hasText: "A task that is refused" })).toBeVisible(),
    undone: async (page) => {
      await expect(page.getByTestId("task-created").filter({ hasText: "A task that is refused" })).toHaveCount(0);
      await expect(page.getByTestId("task-created")).toHaveCount(1); // only the sample announcement is left
    },
  },
  {
    name: "changing progress",
    route: [/\/api\/cards\/[^/]+$/, "PATCH"],
    start: (page) => inRoom(page, "Jalali date picker"),
    act: (page) => page.getByRole("slider", { name: "Progress" }).fill("90"),
    shown: (page) => expect(page.getByTestId("panel-progress")).toHaveText("90%"),
    undone: (page) => expect(page.getByTestId("panel-progress")).toHaveText("35%"),
  },
  {
    name: "adding an assignee",
    route: [/\/api\/cards\/[^/]+\/members$/, "POST"],
    start: (page) => inRoom(page, "Keyboard shortcut sheet"),
    act: (page) => button(page, "+ Ali Rezaei").click(),
    shown: (page) => expect(page.getByTestId("panel-member")).toHaveCount(1),
    undone: (page) => expect(page.getByTestId("panel-member")).toHaveCount(0),
  },
  {
    name: "changing the density",
    route: [/\/api\/settings$/, "PATCH"],
    act: (page) => button(page, "Compact").click(),
    shown: (page) => expect(button(page, "Compact")).toHaveAttribute("aria-pressed", "true"),
    undone: (page) => expect(button(page, "Comfortable")).toHaveAttribute("aria-pressed", "true"),
  },
  {
    name: "changing the language",
    route: [/\/api\/settings$/, "PATCH"],
    act: (page) => setFa(page),
    shown: (page) => expect(page.locator("html")).toHaveAttribute("dir", "rtl"),
    undone: (page) => expect(page.locator("html")).toHaveAttribute("dir", "ltr"),
  },
];

for (const how of ["refuse", "drop"] as const) {
  for (const kind of kinds) {
    test(`${kind.name} is undone with a toast when the server ${how === "refuse" ? "refuses it" : "cannot be reached"}`, async ({ page, errors }) => {
      await kind.start?.(page);
      await failing(page, ...kind.route, how);
      await kind.act(page);

      await kind.shown(page); // at once, before the server has answered
      await expect(toast(page)).toContainText(TOAST_EN);
      await kind.undone(page); // taken back

      // The server never saw it: after a refresh the old state is still there.
      await settled(page);
      await page.unroute(kind.route[0]);
      const before = JSON.stringify((await serverBoard(page)).cards);
      await page.reload();
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(JSON.stringify((await serverBoard(page)).cards)).toBe(before);
      allowFailedRequests(errors);
    });
  }
}

test("the toast is in Persian when the language is Persian, and can be closed", async ({ page, errors }) => {
  await setFa(page);
  await settled(page);
  await failing(page, /\/api\/cards\/[^/]+\/move$/, "POST");
  await card(page, "تست‌های واحد ستون‌ها").getByRole("button").first().focus();
  await page.keyboard.press(","); // RTL: "," moves to the previous column, here Ideas
  await expect(toast(page)).toContainText(TOAST_FA);
  await expect(card(column(page, "todo"), "تست‌های واحد ستون‌ها")).toBeVisible();
  await toast(page).getByRole("button").click();
  await expect(toast(page)).toHaveCount(0);
  allowFailedRequests(errors);
});

test("a refused message in Persian is undone with the Persian toast", async ({ page, errors }) => {
  await setFa(page);
  await settled(page);
  await page.keyboard.press("g");
  await page.keyboard.press("c");
  await failing(page, /\/api\/spaces\/general\/messages$/, "POST");
  await page.getByRole("textbox").fill("پیام ذخیره‌نشده");
  await page.getByRole("textbox").press("Enter");
  await expect(page.getByText("پیام ذخیره‌نشده")).toBeVisible();
  await expect(toast(page)).toContainText(TOAST_FA);
  await expect(page.getByText("پیام ذخیره‌نشده")).toHaveCount(0);
  allowFailedRequests(errors);
});

test("changes queued behind a failed one are dropped with it, and the rest of the board is untouched", async ({ page, errors }) => {
  await failing(page, /\/api\/cards$/, "POST"); // creating the card fails
  await button(page, "Add card to Ideas").click();
  const dialog = page.getByRole("dialog", { name: "New card" });
  await dialog.getByLabel("Title").fill("Doomed card");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(card(column(page, "ideas"), "Doomed card")).toBeVisible();
  await card(column(page, "ideas"), "Doomed card").getByRole("button", { name: "Doomed card" }).focus();
  await page.keyboard.press("."); // moved before the server answered: depends on the card that fails
  await expect(toast(page)).toContainText(TOAST_EN);
  await expect(card(page, "Doomed card")).toHaveCount(0);
  await expect(page.getByTestId("board-count")).toHaveText("10");
  await boardNav(page).click();
  allowFailedRequests(errors);
});

test("a delete that fails brings the card back and closes the undo toast", async ({ page, errors }) => {
  await failing(page, /\/api\/cards\/[^/]+$/, "DELETE");
  const target = card(page, "Column unit tests");
  await target.hover();
  await button(target, "Delete card").click();
  await expect(page.getByTestId("undo-toast")).toBeVisible();
  await expect(toast(page)).toContainText(TOAST_EN);
  await expect(page.getByTestId("undo-toast")).toHaveCount(0);
  await expect(card(page, "Column unit tests")).toHaveCount(1);
  allowFailedRequests(errors);
});

// ---- first load ----------------------------------------------------------------------------------------

test("a skeleton shows while the board loads: no sample data, no empty board", async ({ page, errors }) => {
  await page.route("**/api/board", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.fallback();
  });
  await page.goto("/");
  const skeleton = page.getByRole("status", { name: "Loading your board" });
  await expect(skeleton).toBeVisible();
  await expect(page.getByTestId("card")).toHaveCount(0);
  await expect(page.locator("[data-column-id]")).toHaveCount(0); // not even empty columns
  await expect(page.getByTestId("room")).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(0);
  await expect(page.getByTestId("card").first()).toBeVisible(); // then the real board
  await expect(skeleton).toHaveCount(0);
  await expect(page.getByTestId("card")).toHaveCount(10);
  expect(errors).toEqual([]);
});

test("when the board cannot be reached there is a clear message with Try again", async ({ page, errors }) => {
  await page.route("**/api/board", (route) => route.abort("connectionrefused"));
  await page.goto("/");
  const message = page.getByTestId("unreachable");
  await expect(message).toContainText("Can't reach the server");
  await expect(message).toContainText("ارتباط با سرور برقرار نشد"); // both languages: the user's is not known here
  await expect(page.getByTestId("card")).toHaveCount(0);

  await page.unroute("**/api/board");
  await message.getByRole("button", { name: /Try again/ }).click();
  await expect(page.getByTestId("card").first()).toBeVisible();
  await expect(message).toHaveCount(0);
  allowFailedRequests(errors);
});

test("a failing server is treated like an unreachable one", async ({ page, errors }) => {
  await page.route("**/api/board", (route) => route.fulfill({ status: 500, body: "{}" }));
  await page.goto("/");
  await expect(page.getByTestId("unreachable")).toBeVisible();
  await page.unroute("**/api/board");
  await page.getByTestId("unreachable").getByRole("button", { name: /Try again/ }).click();
  await expect(page.getByTestId("card").first()).toBeVisible();
  allowFailedRequests(errors);
});

test("when the server cannot be reached at all at the first check, Try again waits for it to come back", async ({ page, errors }) => {
  await page.route("**/api/me", (route) => route.abort("connectionrefused"));
  await page.goto("/");
  await expect(page.getByTestId("unreachable")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Welcome back" })).toHaveCount(0); // not mistaken for "signed out"
  await page.unroute("**/api/me");
  await page.getByRole("button", { name: /Try again/ }).click();
  await expect(page.getByTestId("card").first()).toBeVisible();
  allowFailedRequests(errors);
});
