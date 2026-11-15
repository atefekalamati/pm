import { expect, test as base, type Page } from "@playwright/test";
import { createUser, settled, type TestUser } from "./helpers";

/** These tests start signed out, so they use the plain test instead of the signed-in one from helpers. */
const test = base.extend<{ errors: string[]; account: TestUser }>({
  // Every test signs in as its own new user (the language and the board are saved per user on the server).
  account: async ({ page }, provide) => provide(await createUser(page.request)),
  errors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("console", (m) => {
        // The browser logs every 401 answer; those are expected here.
        if (m.type() === "error" && !m.text().includes("401")) errors.push(m.text());
      });
      await use(errors);
      expect(errors).toEqual([]);
    },
    { auto: true },
  ],
});

const signInHeading = (page: Page) => page.getByRole("heading", { level: 2, name: "Welcome back" });
const board = (page: Page) => page.getByTestId("card").first();

async function submit(page: Page, username: string, password: string) {
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function signInWithForm(page: Page, account: TestUser) {
  await page.goto("/");
  await submit(page, account.username, account.password);
  await expect(board(page)).toBeVisible();
}

async function signOutWithMenu(page: Page) {
  await page.getByTestId("profile").getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(signInHeading(page)).toBeVisible();
}

test("the board needs sign-in, and the page shows the Tidy. logo", async ({ page }) => {
  await page.goto("/");
  await expect(signInHeading(page)).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Tidy.");
  await expect(page.getByTestId("card")).toHaveCount(0);
  await expect(page.getByLabel("Username")).toBeFocused();
});

test("a wrong password or username gets the same message, without saying which", async ({ page }) => {
  await page.goto("/");
  const alert = page.locator("form").getByRole("alert");

  await submit(page, "user", "wrong");
  await expect(alert).toHaveText("Incorrect username or password.");
  await expect(page.getByLabel("Password")).toHaveValue("");

  await submit(page, "nobody", "password");
  await expect(alert).toHaveText("Incorrect username or password.");

  // Team members exist but cannot sign in.
  await submit(page, "ali", "password");
  await expect(alert).toHaveText("Incorrect username or password.");
  await expect(page.getByTestId("card")).toHaveCount(0);
});

test("signs in, shows Atefe Kalamati, and a refresh keeps the user signed in", async ({ page, account }) => {
  await signInWithForm(page, account);
  await expect(page.getByTestId("profile")).toContainText("Atefe Kalamati");
  await page.reload();
  await expect(board(page)).toBeVisible();
  await expect(signInHeading(page)).toHaveCount(0);
});

test("signs out from the ⋯ menu; refresh, Back and Forward do not show the board", async ({ page, account }) => {
  await signInWithForm(page, account);
  await signOutWithMenu(page);

  await page.reload();
  await expect(signInHeading(page)).toBeVisible();

  await page.goBack();
  await page.goForward();
  await expect(signInHeading(page)).toBeVisible();
  await expect(page.getByTestId("card")).toHaveCount(0);
});

test("Back to a cached board after signing out elsewhere shows sign-in", async ({ page, account }) => {
  await signInWithForm(page, account);
  await page.goto("/api/health");
  // Signed out from another tab while this one is on another page.
  expect((await page.request.post("/api/logout")).status()).toBe(204);
  await page.goBack();
  await expect(signInHeading(page)).toBeVisible();
  await expect(page.getByTestId("card")).toHaveCount(0);
});

test("the sign-in page has its own language switch and works right-to-left in Persian", async ({ page, account }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "فارسی" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { level: 2, name: "خوش آمدید" })).toBeVisible();

  await page.getByLabel("نام کاربری").fill("user");
  await page.getByLabel("رمز عبور").fill("wrong");
  await page.getByRole("button", { name: "ورود" }).click();
  await expect(page.locator("form").getByRole("alert")).toHaveText("نام کاربری یا رمز عبور نادرست است.");

  // The form sits on the right in Persian.
  const form = (await page.locator("main section").boundingBox())!;
  const label = (await page.getByText("نام کاربری", { exact: true }).boundingBox())!;
  expect(form.x + form.width - (label.x + label.width)).toBeLessThan(40);

  await page.getByLabel("نام کاربری").fill(account.username);
  await page.getByLabel("رمز عبور").fill(account.password);
  await page.getByRole("button", { name: "ورود" }).click();
  await expect(board(page)).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");

  // The language chosen on the sign-in page is saved for the user, so it follows them to any browser.
  await settled(page);
  expect(await (await page.request.get("/api/settings")).json()).toMatchObject({ language: "fa" });
});

test("a session that ends while the board is open returns to sign-in when the tab is used again", async ({ page, account }) => {
  await signInWithForm(page, account);
  await page.keyboard.press("?");
  await expect(page.getByRole("dialog")).toBeVisible();

  expect((await page.request.post("/api/logout")).status()).toBe(204);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));

  await expect(signInHeading(page)).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // Signing in again brings the board back without the old dialog.
  await submit(page, account.username, account.password);
  await expect(board(page)).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("an idle open board notices an ended session within a minute", async ({ page, account }) => {
  await page.clock.install();
  await signInWithForm(page, account);
  await page.context().clearCookies();
  await page.clock.runFor(61_000);
  await expect(signInHeading(page)).toBeVisible();
});
