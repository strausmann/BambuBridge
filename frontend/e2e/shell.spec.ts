import { expect, test as base, type Page } from "@playwright/test";
import { BASE_URL, BOOTSTRAP_HEADER, BOOTSTRAP_KEY, RESET_HEADERS, RESET_PATH } from "./env";

/**
 * Every test starts from a fresh install (empty database, bootstrap open) and fails on any
 * Content-Security-Policy violation and on any request that leaves this origin.
 */
const test = base.extend<{ guard: void }>({
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

/**
 * Screenshots for review are written only when a directory is named; they are artefacts, never a
 * gate. Chromium only: in WebKit Playwright hides the caret with an inline style, which this
 * page's Content-Security-Policy refuses (and the guard above would rightly report).
 */
async function shot(page: Page, name: string): Promise<void> {
  const dir = process.env.E2E_SCREENSHOT_DIR;
  if (dir && test.info().project.name === "chromium") await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true });
}

async function bootstrapToken(page: Page): Promise<string> {
  const created = await page.request.post("/api/v1/admin/api-keys", {
    headers: { [BOOTSTRAP_HEADER]: BOOTSTRAP_KEY },
    data: { name: "First admin token", scope: "admin" },
  });
  expect(created.status()).toBe(201);
  return ((await created.json()) as { token: string }).token;
}

async function signIn(page: Page, token: string): Promise<void> {
  await page.getByLabel("API-Token").fill(token);
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
}

test("first start: the bootstrap key creates an admin token, shown exactly once, and it signs in", async ({ page }) => {
  await page.goto("/");
  // Signed out: the shell sends to the sign-in instead of an empty page.
  await expect(page).toHaveURL(/\/sign-in\?redirect=%2F$/);
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
  await shot(page, "sign-in-light");

  await page.getByRole("link", { name: "Erstes Admin-Token anlegen" }).click();
  await expect(page).toHaveURL(/\/bootstrap$/);
  await page.getByLabel("Bootstrap-Schlüssel").fill(BOOTSTRAP_KEY);
  await page.getByRole("button", { name: "Admin-Token anlegen" }).click();

  const shown = page.getByTestId("admin-token");
  await expect(shown).toBeVisible();
  const token = (await shown.textContent())!;
  expect(token.length).toBeGreaterThan(20);
  await expect(page.getByText("Dieses Token wird nur jetzt angezeigt.")).toBeVisible();
  // The bootstrap key itself is no longer on the page.
  await expect(page.getByLabel("Bootstrap-Schlüssel")).toHaveCount(0);
  await shot(page, "bootstrap-created-light");

  await page.getByRole("button", { name: "Weiter zur Oberfläche" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("signed-in-user")).toHaveText("Angemeldet als admin");
  await shot(page, "shell-light");

  // Exactly once: the token is nowhere in the page or in the browser's storage, a reload does
  // not bring it back, and the first-start screen is gone for a signed-in user.
  const leftovers = () =>
    page.evaluate((value) => document.documentElement.outerHTML.includes(value) || JSON.stringify({ ...localStorage, ...sessionStorage }).includes(value), token);
  expect(await leftovers()).toBe(false);
  await page.goto("/bootstrap");
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  expect(await leftovers()).toBe(false);

  // The server keeps metadata only: no second token can be made, and the list never returns the first one.
  const list = await page.request.get("/api/v1/admin/api-keys");
  expect(list.status()).toBe(200);
  const keys = (await list.json()) as Record<string, unknown>[];
  expect(keys).toHaveLength(1);
  expect(JSON.stringify(keys)).not.toContain(token);

  // Bootstrap is closed now, and the token is what signs in from here on.
  await page.getByRole("button", { name: "Abmelden" }).click();
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
  await page.goto("/bootstrap");
  await page.getByLabel("Bootstrap-Schlüssel").fill(BOOTSTRAP_KEY);
  await page.getByRole("button", { name: "Admin-Token anlegen" }).click();
  await expect(page.getByRole("alert")).toHaveText("Es gibt bereits ein Admin-Token. Melde dich damit an.");
  await page.getByRole("link", { name: "Zurück zur Anmeldung" }).click();
  await signIn(page, token);
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
});

test("the unused admin token is not lost to Back or to a link: the screen asks first", async ({ page }) => {
  await page.goto("/sign-in");
  await page.getByRole("link", { name: "Erstes Admin-Token anlegen" }).click();
  await page.getByLabel("Bootstrap-Schlüssel").fill(BOOTSTRAP_KEY);
  await page.getByRole("button", { name: "Admin-Token anlegen" }).click();
  const shown = page.getByTestId("admin-token");
  await expect(shown).toBeVisible();
  const token = (await shown.textContent())!;

  await page.goBack();
  const question = page.getByRole("alertdialog");
  await expect(question).toContainText("Das Token wird danach nicht mehr angezeigt.");
  await expect(page.getByRole("button", { name: "Hier bleiben" })).toBeFocused();
  await shot(page, "bootstrap-leave-question");
  await page.getByRole("button", { name: "Hier bleiben" }).click();
  await expect(question).toHaveCount(0);
  await expect(page).toHaveURL(/\/bootstrap$/);
  await expect(shown).toHaveText(token);

  // Using the token is not "leaving": no question on the way into the shell.
  await page.getByRole("button", { name: "Weiter zur Oberfläche" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  await expect(question).toHaveCount(0);
});

test("a return target that resolves to another host or to a server path ends on the overview", async ({ page }) => {
  const token = await bootstrapToken(page);
  for (const target of ["/..//evil.example/p", "/.\\/evil.example/p", "/%2e%2e//evil.example/p", "/api/v1/info", "/auth/continue", "/openapi.json", "/docs"]) {
    await page.goto(`/sign-in?redirect=${encodeURIComponent(target)}`);
    await signIn(page, token);
    await expect(page.getByRole("heading", { name: "Übersicht" }), target).toBeVisible();
    expect(new URL(page.url()).pathname, target).toBe("/");
    await page.getByRole("button", { name: "Abmelden" }).click();
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
  }
});

test("the reset path of the test server needs its header", async ({ request }) => {
  expect((await request.post(RESET_PATH)).status()).toBe(403);
  expect((await request.post(RESET_PATH, { headers: { "X-Requested-With": "reset" } })).status()).toBe(403);
});

test("a wrong bootstrap key and a wrong token are refused with a message", async ({ page }) => {
  await page.goto("/bootstrap");
  await page.getByLabel("Bootstrap-Schlüssel").fill("not-the-bootstrap-key-not-the-bootstrap-key");
  await page.getByRole("button", { name: "Admin-Token anlegen" }).click();
  await expect(page.getByRole("alert")).toHaveText("Der Bootstrap-Schlüssel wurde nicht akzeptiert.");
  await expect(page.getByTestId("admin-token")).toHaveCount(0);

  await page.goto("/sign-in");
  await signIn(page, "bb_wrong-token");
  await expect(page.getByRole("alert")).toHaveText("Dieses Token wurde nicht akzeptiert.");
  await expect(page.getByLabel("API-Token")).toHaveValue("");

  // Without a trusted proxy in front, single sign-on explains itself instead of leading nowhere.
  await page.getByRole("button", { name: "Mit einmaliger Anmeldung (SSO) fortfahren" }).click();
  await expect(page.getByRole("alert")).toContainText("Die einmalige Anmeldung hat dich nicht erkannt.");
});

test("sign-in returns to the page the visitor asked for; the session survives a reload; sign-out ends it", async ({ page }) => {
  const token = await bootstrapToken(page);
  await page.goto("/protocol");
  await expect(page).toHaveURL(/\/sign-in\?redirect=%2Fprotocol$/);
  await signIn(page, token);
  await expect(page.getByRole("heading", { name: "Protokoll" })).toBeVisible();
  await expect(page).toHaveURL(/\/protocol$/);

  await page.reload();
  await expect(page.getByRole("heading", { name: "Protokoll" })).toBeVisible();

  // Navigation: the four destinations, the current one marked.
  const sidebar = page.locator("aside");
  await sidebar.getByRole("link", { name: "Anbieter" }).click();
  await expect(page.getByRole("heading", { name: "Anbieter" })).toBeVisible();
  await expect(sidebar.getByRole("link", { name: "Anbieter" })).toHaveAttribute("aria-current", "page");
  await sidebar.getByRole("link", { name: "Einstellungen" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await page.goto("/device");
  await expect(page.getByRole("heading", { name: "Dieses Gerät" })).toBeVisible();

  // Sign-out is a state-changing request: it only succeeds with the session's CSRF token.
  const signedOut = page.waitForResponse((response) => response.url().endsWith("/api/v1/auth/session") && response.request().method() === "DELETE");
  await page.getByRole("button", { name: "Abmelden" }).click();
  expect((await signedOut).status()).toBe(204);
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
  await page.goto("/providers");
  await expect(page).toHaveURL(/\/sign-in\?redirect=%2Fproviders$/);
});

test("theme: the choice applies at once, survives a reload without a light flash, and system follows the device", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  const token = await bootstrapToken(page);
  await page.goto("/sign-in");
  await signIn(page, token);
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();

  const background = () => page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor);
  expect(await background()).toBe("rgb(243, 247, 251)");
  await page.getByRole("radio", { name: "Dunkles Design" }).click({ force: true });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect.poll(background).toBe("rgb(13, 18, 24)");
  await shot(page, "shell-dark");

  // theme-init.js runs before the app: the attribute is set when the document is parsed.
  await page.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      (window as unknown as { themeAtParse: string | null }).themeAtParse = document.documentElement.getAttribute("data-theme");
    });
  });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { themeAtParse: string | null }).themeAtParse)).toBe("dark");
  await expect(page.getByRole("radio", { name: "Dunkles Design" })).toBeChecked();

  await page.getByRole("radio", { name: "Systemdesign" }).click({ force: true });
  await expect(page.locator("html")).not.toHaveAttribute("data-theme");
  await expect.poll(background).toBe("rgb(243, 247, 251)");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect.poll(background).toBe("rgb(13, 18, 24)");

  await page.getByRole("button", { name: "Abmelden" }).click();
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
  await shot(page, "sign-in-dark");
});

test("language: German is the source, English is one press away and remembered", async ({ page }) => {
  await page.goto("/sign-in");
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "de");

  await page.getByRole("button", { name: "Switch to English" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByLabel("API token")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByRole("button", { name: "Auf Deutsch wechseln" }).click();
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
});

test("phone width: tab bar instead of sidebar, and the shell works with it", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 780 });
  const token = await bootstrapToken(page);
  await page.goto("/sign-in");
  await shot(page, "phone-sign-in");
  await signIn(page, token);
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  await expect(page.locator("aside")).toBeHidden();
  const tabs = page.locator("[data-tabbar]");
  await expect(tabs).toBeVisible();
  await shot(page, "phone-shell");
  await tabs.getByRole("link", { name: "Protokoll" }).click();
  await expect(page.getByRole("heading", { name: "Protokoll" })).toBeVisible();
  await expect(tabs.getByRole("link", { name: "Protokoll" })).toHaveAttribute("aria-current", "page");
});

test("the server answers the shell for client-side routes and sends the security headers", async ({ page }) => {
  const response = await page.goto("/settings/access");
  expect(response!.status()).toBe(200);
  const headers = response!.headers();
  expect(headers["content-security-policy"]).toContain("script-src 'self'");
  expect(headers["content-security-policy"]).not.toContain("unsafe-inline");
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
});
