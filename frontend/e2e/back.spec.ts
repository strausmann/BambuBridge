import { expect, shot, signedInAt, test } from "./fixtures";

// Every history write and popstate in the page, with its time, so that a failed Back shows in the
// report what the history held (the router queues its own writes, so their order depends on timing).
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const log: unknown[] = [];
    (window as unknown as { __historyLog: unknown[] }).__historyLog = log;
    const record = (what: string) =>
      log.push({ what, at: Math.round(performance.now()), length: history.length, path: location.pathname, state: history.state as unknown });
    for (const method of ["pushState", "replaceState"] as const) {
      const original = history[method].bind(history);
      history[method] = (...args: Parameters<History["pushState"]>) => {
        original(...args);
        record(method);
      };
    }
    window.addEventListener("popstate", () => record("popstate"));
  });
});

test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status === testInfo.expectedStatus) return;
  const log = await page.evaluate(() => (window as unknown as { __historyLog?: unknown[] }).__historyLog ?? []).catch(() => []);
  await testInfo.attach("history-log", { body: JSON.stringify(log, null, 2), contentType: "application/json" });
});

test("Back closes an open sheet and stays on the page; the next Back leaves as before", async ({ page }) => {
  await signedInAt(page, "/settings");
  await page.getByRole("link", { name: /Dieses Gerät/ }).click();
  await expect(page).toHaveURL(/\/device$/);

  await page.getByRole("button", { name: "Als App installieren" }).click();
  const sheet = page.getByRole("dialog", { name: "Als App installieren" });
  await expect(sheet).toBeVisible();
  await shot(page, "device-install-sheet", { fullPage: false });

  await page.evaluate(() => (window as unknown as { __historyLog: unknown[] }).__historyLog.push({ what: "goBack", at: Math.round(performance.now()) }));
  await page.goBack();
  await expect(sheet).toHaveCount(0);
  await expect(page).toHaveURL(/\/device$/);
  await expect(page.getByRole("heading", { name: "Dieses Gerät" })).toBeVisible();

  // Closed by its own button, the sheet leaves no entry behind: Back goes to the settings.
  await page.getByRole("button", { name: "Als App installieren" }).click();
  await expect(sheet).toBeVisible();
  await page.getByRole("button", { name: "Fertig" }).click();
  await expect(sheet).toHaveCount(0);
  await page.goBack();
  await expect(page).toHaveURL(/\/settings$/);
});
