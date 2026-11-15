import { randomUUID } from "node:crypto";
import { expect, test as base, type APIRequestContext, type Locator, type Page } from "@playwright/test";

/** 17 Aban 1405, the "today" of the sample data. */
export const TODAY = new Date("2026-11-08T11:00:00");
export const TODAY_ISO = "2026-11-08";

export const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

/** The real sample user (sign-in form tests). */
export const CREDENTIALS = { username: "user", password: "password" };

export interface TestUser {
  username: string;
  password: string;
}

/**
 * A new user with their own sample board, dated from TODAY. The server must run with TIDY_E2E=1
 * (backend/app/e2e.py): Playwright tests share one server, so each test gets a user nobody else touches.
 */
export async function createUser(request: APIRequestContext, username = `e2e-${randomUUID().slice(0, 8)}`): Promise<TestUser> {
  const response = await request.post("/api/e2e/users", { data: { username, today: TODAY_ISO } });
  expect(response.status(), "is the server running with TIDY_E2E=1?").toBe(201);
  return response.json();
}

/** Signs in through the API; the page shares the cookie. Makes a new user unless one is given. */
export async function login(page: Page, user?: TestUser) {
  const who = user ?? (await createUser(page.request));
  const response = await page.request.post("/api/login", { data: who });
  expect(response.ok()).toBe(true);
  return who;
}

/** Every test starts signed in as its own new user, on the board. Sign-in itself is tested in auth.spec.ts. */
export const test = base.extend<{ errors: string[]; user: TestUser }>({
  user: async ({ page }, provide) => provide(await createUser(page.request)),
  errors: [
    async ({ page, user }, use) => {
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("console", (m) => {
        if (m.type() === "error") errors.push(m.text());
      });
      await page.clock.setFixedTime(TODAY);
      await login(page, user);
      await page.goto("/");
      await expect(page.getByTestId("card").first()).toBeVisible();
      await use(errors);
      expect(errors).toEqual([]);
    },
    { auto: true },
  ],
});

export { expect, base as plainTest };

export const column = (page: Page, id: string) => page.getByTestId(`column-${id}`);
export const card = (scope: Page | Locator, title: string) => scope.getByTestId("card").filter({ hasText: title });
export const button = (scope: Page | Locator, name: string | RegExp) =>
  scope.getByRole("button", typeof name === "string" ? { name, exact: true } : { name });
export const composer = (page: Page) => page.getByRole("textbox", { name: "Write a message…" });

export const setFa = (page: Page) => button(page, "فارسی").click();
export const setEn = (page: Page) => button(page, "English").click();
export const boardNav = (page: Page) => page.getByRole("button", { name: /^Project board/ });

export async function openRoom(page: Page, title: string) {
  await card(page, title).getByRole("button", { name: title }).click();
  await expect(page.getByRole("heading", { level: 2, name: title })).toBeVisible();
}

/** Waits until every change shown on screen has reached the server (the app sets data-saving on <html>). */
export async function settled(page: Page) {
  await page.waitForFunction(() => document.documentElement.dataset.saving !== "true");
}

/** Reloads, after the last change has been saved, and waits until the board has been loaded from the server. */
export async function reload(page: Page) {
  await settled(page);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

export async function drag(page: Page, source: Locator, target: Locator, { drop = true } = {}) {
  const from = (await source.boundingBox())!;
  const to = (await target.boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2 + 10, from.y + from.height / 2, { steps: 5 });
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 20 });
  if (drop) await page.mouse.up();
}

/** Picks up the focused card, then waits for dnd-kit to measure it: earlier arrow keys are ignored. */
export async function pickUp(page: Page) {
  await page.keyboard.press("Space");
  await expect(page.getByTestId("drag-overlay")).toBeVisible();
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
}

/** Draws an image in the browser and returns its bytes; noise is 0 for a flat image. */
export async function makeImage(
  page: Page,
  { width, height, alpha = 255, noise = 0 }: { width: number; height: number; alpha?: number; noise?: number },
) {
  const base64 = await page.evaluate(
    ({ width, height, alpha, noise }) => {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d")!;
      const image = context.createImageData(width, height);
      let seed = 7;
      const random = () => (seed = (seed * 48271) % 2147483647) / 2147483647;
      for (let i = 0; i < image.data.length; i += 4) {
        image.data[i] = 120 + random() * noise;
        image.data[i + 1] = 150 + random() * noise;
        image.data[i + 2] = 180 + random() * noise;
        image.data[i + 3] = alpha;
      }
      context.putImageData(image, 0, 0);
      return canvas.toDataURL("image/png").split(",")[1];
    },
    { width, height, alpha, noise },
  );
  return Buffer.from(base64, "base64");
}
