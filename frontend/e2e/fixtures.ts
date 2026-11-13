import { expect, test as base, type Page } from "@playwright/test";
import { BASE_URL, BOOTSTRAP_HEADER, BOOTSTRAP_KEY, RESET_HEADERS, RESET_PATH } from "./env";

/**
 * Every test starts from a fresh install (empty database, bootstrap open, the first build) and
 * fails on any Content-Security-Policy violation and on any request that leaves this origin.
 */
export const test = base.extend<{ guard: void }>({
  guard: [
    async ({ page, request }, use) => {
      expect(BOOTSTRAP_KEY.length, "E2E_BOOTSTRAP_KEY is set by playwright.config.ts").toBeGreaterThanOrEqual(32);
      expect((await request.post(RESET_PATH, { headers: RESET_HEADERS })).status()).toBe(204);
      const violations: string[] = [];
      const foreign: string[] = [];
      page.on("console", (message) => {
        if (/content security policy/i.test(message.text())) violations.push(message.text());
      });
      page.on("request", (sent) => {
        const url = sent.url();
        if (!url.startsWith(`${BASE_URL}/`) && !url.startsWith("data:") && !url.startsWith("blob:")) foreign.push(url);
      });
      await use();
      expect(violations, "Content-Security-Policy violations").toEqual([]);
      expect(foreign, "requests to another origin").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/**
 * Screenshots for review are written only when a directory is named; they are artefacts, never a
 * gate. Chromium projects only: in WebKit Playwright hides the caret with an inline style, which
 * this page's Content-Security-Policy refuses (and the guard above would rightly report).
 */
export async function shot(page: Page, name: string, options: { fullPage?: boolean } = {}): Promise<void> {
  const dir = process.env.E2E_SCREENSHOT_DIR;
  if (dir && test.info().project.name.endsWith("chromium")) await page.screenshot({ path: `${dir}/${name}.png`, fullPage: options.fullPage ?? true });
}

export async function bootstrapToken(page: Page): Promise<string> {
  const created = await page.request.post("/api/v1/admin/api-keys", {
    headers: { [BOOTSTRAP_HEADER]: BOOTSTRAP_KEY },
    data: { name: "First admin token", scope: "admin" },
  });
  expect(created.status()).toBe(201);
  return ((await created.json()) as { token: string }).token;
}

export async function signIn(page: Page, token: string): Promise<void> {
  await page.getByLabel("API-Token").fill(token);
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
}

/** A fresh install, signed in with its first admin token, on `path`. */
export async function signedInAt(page: Page, path: string): Promise<void> {
  const token = await bootstrapToken(page);
  await page.goto(path);
  await signIn(page, token);
  // On a loaded machine (load average above the core count) the sign-in request has stayed
  // pending past the default five seconds without failing; the wait is for the sign-in, not a
  // speed check.
  await expect(page.getByTestId("signed-in-user")).toBeAttached({ timeout: 20_000 });
}

/** The page is controlled by the service worker (the shell came from its cache). */
export async function waitForWorker(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await expect.poll(() => page.evaluate(() => navigator.serviceWorker.controller !== null), { message: "service worker controls the page" }).toBe(true);
}

/** Opens a main destination: the tab bar below 1024 px (tapped on a touch device), the sidebar from there. */
export async function openMain(page: Page, name: string): Promise<void> {
  const link = page.getByRole("navigation", { name: "Hauptnavigation" }).filter({ visible: true }).getByRole("link", { name });
  if (test.info().project.use.hasTouch) await link.tap();
  else await link.click();
}
