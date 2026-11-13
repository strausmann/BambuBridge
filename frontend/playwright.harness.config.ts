import { defineConfig, devices } from "@playwright/test";

// Real-browser layout checks of the shell without a backend (jsdom has no layout engine):
// the page is harness/*.html on the vite dev server, the API is answered inside the page.
export const HARNESS_URL = "http://127.0.0.1:5199";

export default defineConfig({
  testDir: "./harness",
  testMatch: "**/*.spec.ts",
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: "list",
  use: { baseURL: HARNESS_URL, locale: "de-DE" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    command: "pnpm exec vite --host 127.0.0.1 --port 5199 --strictPort",
    url: `${HARNESS_URL}/harness/shell.html`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
