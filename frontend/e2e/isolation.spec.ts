import type { Page } from "@playwright/test";
import { button, card, column, composer, createUser, expect, login, makeImage, plainTest, reload, test } from "./helpers";

/** What user A did on their board must never show up for user B. */
async function makeAChanges(page: Page) {
  await button(page, "Add card to Ideas").click();
  const dialog = page.getByRole("dialog", { name: "New card" });
  await dialog.getByLabel("Title").fill("A's secret card");
  await dialog.getByRole("button", { name: "Save" }).click();
  const ideas = column(page, "ideas");
  await button(ideas, "Ideas column menu").click();
  await ideas.getByRole("menuitem", { name: "Rename column" }).click();
  await ideas.getByRole("textbox").fill("A's column");
  await ideas.getByRole("textbox").press("Enter");
  await button(page, "Compact").click();
  await page.getByRole("button", { name: /^Chat/ }).click();
  await composer(page).fill("A's secret message");
  await composer(page).press("Enter");
  const buffer = await makeImage(page, { width: 10, height: 10 });
  await page.getByLabel("Attach image").setInputFiles({ name: "a-secret.png", mimeType: "image/png", buffer });
  await expect(page.getByRole("img", { name: "a-secret.png" })).toBeVisible();
  await page.keyboard.press("Escape");
}

async function expectPristine(page: Page) {
  await page.keyboard.press("g");
  await page.keyboard.press("b");
  await expect(page.getByTestId("card")).toHaveCount(10);
  await expect(card(page, "A's secret card")).toHaveCount(0);
  await expect(column(page, "ideas").getByRole("heading")).toHaveText("Ideas");
  await expect(button(page, "Comfortable")).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("g");
  await page.keyboard.press("c");
  await expect(page.getByText("A's secret message")).toHaveCount(0);
  await expect(page.getByRole("img", { name: "a-secret.png" })).toHaveCount(0);
}

test("a second user does not see the first user's board, in another browser", async ({ page, browser }, testInfo) => {
  await makeAChanges(page);
  await page.waitForFunction(() => document.documentElement.dataset.saving !== "true");

  const other = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
  try {
    const b = await other.newPage();
    await login(b); // a new user
    await b.goto("/");
    await expect(b.getByTestId("profile")).toBeVisible();
    await expectPristine(b);
    await expect(b.getByTestId("profile")).toContainText("Atefe Kalamati"); // the same sample people, their own board
  } finally {
    await other.close();
  }

  // And A still has everything.
  await reload(page);
  await page.keyboard.press("g");
  await page.keyboard.press("b");
  await expect(card(page, "A's secret card")).toHaveCount(1);
});

test("signing out and signing in as another user on the same browser leaves nothing of the first", async ({ page }) => {
  await makeAChanges(page);
  await page.waitForFunction(() => document.documentElement.dataset.saving !== "true");
  const second = await createUser(page.request);

  await page.getByTestId("profile").locator("button[aria-haspopup=menu]").click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page.locator('input[name="username"]')).toBeVisible();
  await expect(page.getByTestId("card")).toHaveCount(0); // nothing of A on the sign-in page
  await page.locator('input[name="username"]').fill(second.username);
  await page.locator('input[name="password"]').fill(second.password);
  await page.locator("button[type=submit]").click();
  await expect(page.getByTestId("profile")).toBeVisible(); // the open view is a light preference of this browser: it may be the chat
  await expectPristine(page);
});

test("the second user cannot reach the first user's cards, messages or images through the API either", async ({ page, browser }, testInfo) => {
  await makeAChanges(page);
  await page.waitForFunction(() => document.documentElement.dataset.saving !== "true");
  const mine = await (await page.request.get("/api/board")).json();
  const secretCard = Object.values<{ id: string; title: unknown }>(mine.cards).find((c) => c.title === "A's secret card")!;
  const secretImage = Object.values<{ image?: { src: string } }[]>(mine.messages).flat().find((m) => m.image?.src)!.image!.src;
  expect((await page.request.get(secretImage)).status()).toBe(200);

  const other = await browser.newContext({ baseURL: testInfo.project.use.baseURL });
  try {
    const b = await other.newPage();
    await login(b);
    expect((await b.request.get(secretImage)).status()).toBe(404);
    expect((await b.request.patch(`/api/cards/${secretCard.id}`, { data: { title: "stolen" } })).status()).toBe(404);
    expect((await b.request.delete(`/api/cards/${secretCard.id}`)).status()).toBe(404);
    expect((await b.request.post(`/api/spaces/${secretCard.id}/messages`, { data: { text: "hi" } })).status()).toBe(404);
    const theirs = await (await b.request.get("/api/board")).json();
    expect(JSON.stringify(theirs)).not.toContain("A's secret");
    expect(Object.keys(theirs.cards)).not.toContain(secretCard.id);
  } finally {
    await other.close();
  }
  const still = await (await page.request.get("/api/board")).json();
  expect(still.cards[secretCard.id].title).toBe("A's secret card");
});

plainTest("nobody can see a board without signing in", async ({ request }) => {
  for (const path of ["/api/board", "/api/settings", "/api/images/anything"]) expect((await request.get(path)).status()).toBe(401);
});
