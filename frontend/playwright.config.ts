import { randomBytes } from "node:crypto";
import { defineConfig, devices } from "@playwright/test";
import { BASE_URL, PORT } from "./e2e/env";

// One random bootstrap key per run. The server (started below) and the test workers are child
// processes and inherit it; a worker that loads this file again keeps the value it inherited.
process.env.E2E_BOOTSTRAP_KEY ??= randomBytes(32).toString("base64url");

// The server under test is the real backend serving the production build on a throw-away
// PostgreSQL database: `backend/tests/e2e_app.py` (needs BAMBUBRIDGE_TEST_DATABASE_URL).
// `E2E_PYTHON` overrides the interpreter command (default: the backend's uv environment).
const python = process.env.E2E_PYTHON ?? "uv run --frozen python";
// The update test needs a second build with another build id: the server switches to it on
// request (POST /__e2e/next-build) as a deployment would. Same version, other BUILD_ID.
const nextBuildId = process.env.E2E_NEXT_BUILD_ID ?? "e2e-next";
const buildNext = `BAMBUBRIDGE_BUILD_ID=${nextBuildId} pnpm exec vite build --outDir dist-next --emptyOutDir --logLevel warn`;
const serve =
  `cd ../backend && E2E_PORT=${PORT} E2E_WEB_DIST_DIR=../frontend/dist E2E_WEB_DIST_NEXT_DIR=../frontend/dist-next E2E_NEXT_BUILD_ID=${nextBuildId} ` +
  `${python} -m uvicorn tests.e2e_app:app --host 127.0.0.1 --port ${PORT} --log-level warning`;

/** Every page is the same app; the device classes differ in size and in touch. */
const browsers = { chromium: devices["Desktop Chrome"], webkit: devices["Desktop Safari"] } as const;
type BrowserName = keyof typeof browsers;
const touch = (browser: BrowserName, width: number, height: number) => ({ ...browsers[browser], viewport: { width, height }, hasTouch: true, isMobile: true });

// Which specs run where: the worker specs in every project (checked when this was built:
// Playwright's WebKit on Linux registers, updates and serves offline as Chromium does), the
// shell on the desktop, the phone layout and navigation on phone and tablet sizes.
const WORKER = /(session-expired|update|offline|worker-routes)\.spec\.ts$/;
const DESKTOP = [/(shell|providers|protocol|settings)\.spec\.ts$/, WORKER];
const HANDHELD = [/(layout|navigation|back)\.spec\.ts$/, WORKER];

export default defineConfig({
  testDir: "./e2e",
  // One server and one database: the tests reset it and run one after another.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: BASE_URL, trace: "retain-on-failure", locale: "de-DE" },
  projects: [
    { name: "desktop-chromium", testMatch: DESKTOP, use: browsers.chromium },
    { name: "desktop-webkit", testMatch: DESKTOP, use: browsers.webkit },
    { name: "phone-chromium", testMatch: HANDHELD, use: touch("chromium", 375, 780) },
    { name: "phone-webkit", testMatch: HANDHELD, use: touch("webkit", 375, 780) },
    { name: "tablet-chromium", testMatch: HANDHELD, use: touch("chromium", 820, 1180) },
    { name: "tablet-webkit", testMatch: HANDHELD, use: touch("webkit", 820, 1180) },
    // A phone with the on-screen keyboard open (the layout viewport shrinks with it).
    { name: "short-chromium", testMatch: WORKER, use: touch("chromium", 390, 400) },
    { name: "short-webkit", testMatch: WORKER, use: touch("webkit", 390, 400) },
    // A laptop with little height.
    { name: "short-wide-chromium", testMatch: WORKER, use: { ...browsers.chromium, viewport: { width: 1280, height: 500 } } },
  ],
  webServer: {
    command: `pnpm build && ${buildNext} && ${serve}`,
    url: `${BASE_URL}/healthz`,
    reuseExistingServer: false,
    timeout: 240_000,
  },
});
