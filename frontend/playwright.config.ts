import { defineConfig, devices } from "@playwright/test";

// Set PLAYWRIGHT_BASE_URL (for example http://localhost:8001) to test a running container instead of the dev server.
// That server must run with TIDY_E2E=1, so each test can create its own user (see frontend/AGENTS.md).
const externalURL = process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: externalURL ?? "http://localhost:3000",
    trace: "on-first-retry",
    // The server stamps messages in UTC and the screen shows local time: fix the browser's zone so sample times are the same everywhere.
    timezoneId: "UTC",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1860, height: 900 } } }],
  // Without an external URL: the FastAPI backend on 8000 with its own test database and TIDY_E2E=1
  // (dev rewrites send /api there), and the Next.js dev server.
  webServer: externalURL
    ? undefined
    : [
        {
          command: "uv run --directory ../backend uvicorn app.main:app --port 8000",
          url: "http://localhost:8000/api/health",
          env: { TIDY_E2E: "1", DATABASE_PATH: "data/e2e.db" },
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
        {
          command: "npm run dev",
          url: "http://localhost:3000",
          reuseExistingServer: !process.env.CI,
          timeout: 180_000,
        },
      ],
});
