import { defineConfig, devices } from "@playwright/test";
import { BASE_URL, PORT } from "./e2e/env";

// The server under test is the real backend serving the production build on a throw-away
// PostgreSQL database: `backend/tests/e2e_app.py` (needs BAMBUBRIDGE_TEST_DATABASE_URL).
// `E2E_PYTHON` overrides the interpreter command (default: the backend's uv environment).
const python = process.env.E2E_PYTHON ?? "uv run --frozen python";
const serve =
  `cd ../backend && E2E_PORT=${PORT} E2E_WEB_DIST_DIR=../frontend/dist ` + `${python} -m uvicorn tests.e2e_app:app --host 127.0.0.1 --port ${PORT} --log-level warning`;

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  // One server and one database: the tests reset it and run one after another.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: BASE_URL, trace: "retain-on-failure", locale: "de-DE" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    command: `pnpm build && ${serve}`,
    url: `${BASE_URL}/healthz`,
    reuseExistingServer: false,
    timeout: 240_000,
  },
});
