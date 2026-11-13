import type { Page } from "@playwright/test";
import { expect, shot, signedInAt, test } from "./fixtures";

// Every history write and popstate in the page, with its time, so that a failed Back shows in the
// report what the history held (the router queues its own writes, so their order depends on timing).
// The Back presses themselves are noted by the test (`goBack` below) with the same clock (`epoch`),
// so the report shows where each one fell between the page's own entries.
// Also a switch that holds animation frames back: with it the test decides that Back arrives
// before the overlay has revealed itself, instead of hoping the machine is slow enough.
test.beforeEach(async ({ page, browserName, hasTouch }) => {
  // A phone reports touch points; Playwright's WebKit does not, even with touch enabled.
  if (hasTouch) {
    await page.addInitScript(() => {
      if (navigator.maxTouchPoints === 0) Object.defineProperty(Navigator.prototype, "maxTouchPoints", { get: () => 5 });
    });
  }
  await page.addInitScript(() => {
    const log: unknown[] = [];
    (window as unknown as { __historyLog: unknown[] }).__historyLog = log;
    const record = (what: string) =>
      log.push({ what, at: Math.round(performance.now()), epoch: Math.round(performance.timeOrigin + performance.now()), length: history.length, path: location.pathname, state: history.state as unknown });
    for (const method of ["pushState", "replaceState"] as const) {
      const original = history[method].bind(history);
      history[method] = (...args: Parameters<History["pushState"]>) => {
        original(...args);
        record(method);
      };
    }
    window.addEventListener("popstate", () => record("popstate"));

    const frames = { hold: false, queue: [] as FrameRequestCallback[] };
    (window as unknown as { __frames: typeof frames & { release: () => void } }).__frames = Object.assign(frames, {
      release: () => {
        frames.hold = false;
        for (const callback of frames.queue.splice(0)) originalFrame(callback);
      },
    });
    const originalFrame = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (callback) => (frames.hold ? (frames.queue.push(callback), 0) : originalFrame(callback));
  });
  // For looping this spec on a fast machine: E2E_CPU_THROTTLE=4 slows Chromium's main thread down.
  const throttle = Number(process.env.E2E_CPU_THROTTLE ?? 0);
  if (throttle > 1 && browserName === "chromium") {
    await (await page.context().newCDPSession(page)).send("Emulation.setCPUThrottlingRate", { rate: throttle });
  }
});

// Back presses by `goBack`: when the command went out and when it returned (wall clock, as `epoch`).
const goBackMarks = new WeakMap<Page, { what: "goBack"; sentAt: number; returnedAt: number }[]>();

/** `page.goBack()`, noted for the history log. Nothing is evaluated in the page first: no delay. */
async function goBack(page: Page): Promise<void> {
  const sentAt = Date.now();
  await page.goBack();
  goBackMarks.set(page, [...(goBackMarks.get(page) ?? []), { what: "goBack", sentAt, returnedAt: Date.now() }]);
}

test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status === testInfo.expectedStatus) return;
  const log = await page.evaluate(() => (window as unknown as { __historyLog?: unknown[] }).__historyLog ?? []).catch(() => []);
  await testInfo.attach("history-log", { body: JSON.stringify({ page: log, goBack: goBackMarks.get(page) ?? [] }, null, 2), contentType: "application/json" });
});

test("Back closes an open sheet and stays on the page; the next Back leaves as before", async ({ page }) => {
  await signedInAt(page, "/settings");
  await page.getByRole("link", { name: /Dieses Gerät/ }).click();
  await expect(page).toHaveURL(/\/device$/);

  await page.getByRole("button", { name: "Als App installieren" }).click();
  const sheet = page.getByRole("dialog", { name: "Als App installieren" });
  await expect(sheet).toBeVisible();
  await shot(page, "device-install-sheet", { fullPage: false });

  await goBack(page);
  await expect(sheet).toHaveCount(0);
  await expect(page).toHaveURL(/\/device$/);
  await expect(page.getByRole("heading", { name: "Dieses Gerät" })).toBeVisible();

  // Closed by its own button, the sheet leaves no entry behind: Back goes to the settings.
  await page.getByRole("button", { name: "Als App installieren" }).click();
  await expect(sheet).toBeVisible();
  await page.getByRole("button", { name: "Fertig" }).click();
  await expect(sheet).toHaveCount(0);
  await goBack(page);
  await expect(page).toHaveURL(/\/settings$/);
});

type Frames = { __frames: { hold: boolean; release: () => void } };

/** A page loaded on its own: no text field has had the focus, so a touch device may open the keyboard. */
async function freshDevicePage(page: Page): Promise<void> {
  await signedInAt(page, "/settings");
  await page.goto("/device");
  await expect(page.getByRole("button", { name: "Als App installieren" })).toBeVisible();
}

// On a touch device React Aria reveals an overlay two frames after it opened (it waits to see whether
// an on-screen keyboard comes up). A close within those frames used to leave the sheet stuck on screen,
// half-way out (data-exiting), for good: the late reveal cancelled the exit transitions it waited for.
test("Back before the sheet has revealed itself closes it all the same", async ({ page }) => {
  await freshDevicePage(page);
  await page.evaluate(() => {
    (window as unknown as Frames).__frames.hold = true;
  });
  await page.getByRole("button", { name: "Als App installieren" }).click();
  const sheet = page.getByRole("dialog", { name: "Als App installieren" });
  await expect(sheet).toBeAttached();
  // The window this test is about: the panel is still hidden, waiting for its frames.
  expect(await page.locator(".overlay-panel").evaluate((panel) => (panel as HTMLElement).style.clipPath)).toBe("inset(50%)");

  await goBack(page);
  await expect(page).toHaveURL(/\/device$/);
  await page.evaluate(() => (window as unknown as Frames).__frames.release());
  await expect(sheet).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Dieses Gerät" })).toBeVisible();
  await goBack(page);
  await expect(page).toHaveURL(/\/settings$/);
});

// The same without held frames: Back as soon as the sheet is there, as a quick thumb would. A smoke
// test, not a regression test: whether Back lands inside the reveal window depends on the speed of
// the machine, so it can pass on the unfixed code; the test above is the one that is red there.
test("smoke: Back right after the sheet appeared closes it", async ({ page }) => {
  await freshDevicePage(page);
  await page.getByRole("button", { name: "Als App installieren" }).click();
  const sheet = page.getByRole("dialog", { name: "Als App installieren" });
  await expect(sheet).toBeAttached();
  await goBack(page);
  await expect(sheet).toHaveCount(0);
  await expect(page).toHaveURL(/\/device$/);
});
