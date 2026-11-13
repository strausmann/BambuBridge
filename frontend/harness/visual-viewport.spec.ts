import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * iOS Safari with the on-screen keyboard open: the layout viewport keeps its full height and
 * only the visual viewport shrinks and scrolls (here 300 px high, 120 px down). The media
 * queries cannot see that; `--vvh` and `--vv-top` (useVisualViewport.tsx) carry it to the
 * overlays. On a tall page (390 x 780) a test of the media queries alone would pass.
 */
const TOP = 120;
const HEIGHT = 300;

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    class FakeVisualViewport extends EventTarget {
      width = window.innerWidth;
      height = window.innerHeight;
      offsetTop = 0;
      offsetLeft = 0;
      pageTop = 0;
      pageLeft = 0;
      scale = 1;
      onresize = null;
      onscroll = null;
      onscrollend = null;
    }
    const fake = new FakeVisualViewport();
    Object.defineProperty(window, "visualViewport", { configurable: true, get: () => fake });
    (window as unknown as { openKeyboard: (top: number, height: number) => void }).openKeyboard = (top, height) => {
      fake.offsetTop = top;
      fake.height = height;
      fake.dispatchEvent(new Event("resize"));
      fake.dispatchEvent(new Event("scroll"));
    };
  });
});

async function inside(page: Page, locator: Locator, what: string): Promise<void> {
  await expect(page.locator("[data-entering]")).toHaveCount(0);
  await page.waitForFunction(() => document.getAnimations().every((animation) => animation.playState !== "running"));
  const box = await locator.boundingBox();
  expect(box, what).not.toBeNull();
  expect(box!.y, `${what}: top edge`).toBeGreaterThanOrEqual(TOP - 0.5);
  expect(box!.y + box!.height, `${what}: bottom edge`).toBeLessThanOrEqual(TOP + HEIGHT + 0.5);
}

test("with only the visual viewport shrunk (iOS keyboard), the sheet, the field, its first match and the main button stay in it", async ({ page }) => {
  await page.goto("/harness/overlays.html?open=sheet");
  const sheet = page.getByRole("dialog", { name: "Drucker zuweisen" });
  await expect(sheet).toBeVisible();
  await page.evaluate(([top, height]) => (window as unknown as { openKeyboard: (t: number, h: number) => void }).openKeyboard(top!, height!), [TOP, HEIGHT]);
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--vv-top"))).toBe(`${TOP}px`);

  await inside(page, sheet, "panel");
  const field = page.getByRole("combobox", { name: "Drucker" });
  await field.scrollIntoViewIfNeeded();
  await inside(page, field, "field");
  await field.fill("P1");
  const first = page.getByRole("option").first();
  await expect(first).toBeVisible();
  await inside(page, first, "first match");
  await page.keyboard.press("Escape");

  const main = sheet.getByRole("button", { name: "Übernehmen" });
  await main.scrollIntoViewIfNeeded();
  await inside(page, main, "main button");
});
