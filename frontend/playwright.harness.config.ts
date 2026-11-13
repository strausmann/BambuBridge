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
    { name: "chromium", testIgnore: /(keyboard|visual-viewport|popover-reveal)\.spec\.ts$/, use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", testIgnore: /(keyboard|visual-viewport|popover-reveal)\.spec\.ts$/, use: { ...devices["Desktop Safari"] } },
    // A phone with the on-screen keyboard open (the layout viewport shrinks with it), and a laptop
    // with little height: the same short projects as playwright.config.ts.
    { name: "short-chromium", testMatch: /(keyboard|popover-reveal)\.spec\.ts$/, use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 400 }, hasTouch: true, isMobile: true } },
    { name: "short-webkit", testMatch: /(keyboard|popover-reveal)\.spec\.ts$/, use: { ...devices["Desktop Safari"], viewport: { width: 390, height: 400 }, hasTouch: true, isMobile: true } },
    // A tall phone whose visual viewport alone shrinks (iOS Safari with the keyboard open).
    { name: "tall-chromium", testMatch: /visual-viewport\.spec\.ts$/, use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 780 }, hasTouch: true, isMobile: true } },
    { name: "tall-webkit", testMatch: /visual-viewport\.spec\.ts$/, use: { ...devices["Desktop Safari"], viewport: { width: 390, height: 780 }, hasTouch: true, isMobile: true } },
    { name: "short-wide-chromium", testMatch: /keyboard\.spec\.ts$/, use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 500 } } },
  ],
  webServer: {
    command: "pnpm exec vite --host 127.0.0.1 --port 5199 --strictPort",
    url: `${HARNESS_URL}/harness/shell.html`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
