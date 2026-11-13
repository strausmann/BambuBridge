import { expect, test, type Locator, type Page } from "@playwright/test";

// For looping this spec on a fast machine: HARNESS_CPU_THROTTLE=4 slows Chromium's main thread down.
test.beforeEach(async ({ page, browserName }) => {
  const throttle = Number(process.env.HARNESS_CPU_THROTTLE ?? 0);
  if (throttle > 1 && browserName === "chromium") {
    await (await page.context().newCDPSession(page)).send("Emulation.setCPUThrottlingRate", { rate: throttle });
  }
});

/** Nothing is on its way in or out: no enter state is set and no transition or animation runs. */
async function atRest(page: Page): Promise<void> {
  await expect(page.locator("[data-entering]")).toHaveCount(0);
  await page.waitForFunction(() => document.getAnimations().every((animation) => animation.playState !== "running"));
}

/** Inside the visible part of the page (the visual viewport: above the on-screen keyboard). */
async function visible(page: Page, locator: Locator, what: string): Promise<void> {
  // Measured once the enter animations are over, not on their way in.
  await atRest(page);
  const box = await locator.boundingBox();
  expect(box, what).not.toBeNull();
  const view = await page.evaluate(() => {
    const v = window.visualViewport!;
    return { top: v.offsetTop, height: v.height, width: v.width };
  });
  expect(box!.y, `${what}: top edge`).toBeGreaterThanOrEqual(view.top - 0.5);
  expect(box!.y + box!.height, `${what}: bottom edge`).toBeLessThanOrEqual(view.top + view.height + 0.5);
  expect(box!.x + box!.width, `${what}: right edge`).toBeLessThanOrEqual(view.width + 0.5);
}

for (const kind of ["sheet", "dialog"] as const) {
  test(`${kind}: with the keyboard open the field, its first match and the main button stay in sight`, async ({ page }) => {
    await page.goto(`/harness/overlays.html?open=${kind}`);
    const dialog = page.getByRole("dialog", { name: "Drucker zuweisen" });
    await expect(dialog).toBeVisible();
    // The panel never ends below the visible part, whatever its content.
    await visible(page, dialog, "panel");

    const field = page.getByRole("combobox", { name: "Drucker" });
    await field.click();
    await field.fill("P1");
    const first = page.getByRole("option").first();
    await expect(first).toBeVisible();
    await visible(page, page.getByRole("listbox").locator(".."), "list");
    await visible(page, field, "field");
    await visible(page, first, "first match");
    await expect(first).toHaveText("P1S Keller");
    await page.keyboard.press("Escape");

    // The main button comes last inside the scrolling content: reached by scrolling, never cut off.
    const main = dialog.getByRole("button", { name: "Übernehmen" });
    await main.scrollIntoViewIfNeeded();
    await visible(page, main, "main button");
    if (kind === "sheet" && test.info().project.name === "short-chromium" && process.env.E2E_SCREENSHOT_DIR) {
      await field.click();
      await field.fill("A");
      await expect(page.getByRole("option").first()).toBeVisible();
      // The picture shows the list at rest, not on its way in.
      await expect(page.locator("[data-entering], [data-exiting]")).toHaveCount(0);
      await page.waitForFunction(() => document.getAnimations().every((animation) => animation.playState !== "running"));
      await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/phone-sheet-keyboard.png` });
    }
  });
}

/**
 * The boxes of the field and of the list (the popover, the list's scrolling frame), taken once the
 * layout has stopped moving: the same in three animation frames in a row. Both come from one
 * snapshot, so nothing can move between the two measurements.
 */
async function settledBoxes(page: Page) {
  return page.evaluate(
    () =>
      new Promise<{ field: DOMRectInit; popover: DOMRectInit; placement: string | null; view: number }>((resolve) => {
        const read = () => {
          const field = document.querySelector("input[role=combobox]")!.getBoundingClientRect();
          const popover = document.querySelector("[role=listbox]")!.parentElement!;
          const box = popover.getBoundingClientRect();
          const round = (r: DOMRect) => ({ x: r.x, y: r.y, width: r.width, height: r.height });
          return { field: round(field), popover: round(box), placement: popover.getAttribute("data-placement"), view: window.visualViewport!.height };
        };
        let last = JSON.stringify(read());
        let same = 0;
        const frame = () => {
          const now = JSON.stringify(read());
          same = now === last ? same + 1 : 0;
          last = now;
          if (same >= 3) resolve(JSON.parse(now));
          else requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
      }),
  );
}

test("the list flips above the field when there is no room below it", async ({ page }) => {
  await page.goto("/harness/overlays.html?open=sheet&low=1");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  // The sheet must have come to rest, with its fonts, before anything is scrolled or measured.
  await atRest(page);
  await page.evaluate(() => document.fonts.ready);
  // Scroll the content to its end: the field now sits at the bottom of the visible part.
  await dialog.evaluate((element) => {
    const body = element.querySelector(".overflow-y-auto")!;
    body.scrollTop = body.scrollHeight;
  });
  const field = page.getByRole("combobox", { name: "Drucker" });
  // The click may scroll the content once more: Playwright tries another alignment when the first
  // attempt finds the field covered. The field is therefore not at one fixed place when the list
  // opens, and the test must not depend on which place it was.
  await field.click();
  const list = page.getByRole("listbox");
  await expect(list).toBeVisible();
  // The popover (the list's scrolling frame) is what can be seen of the list. React Aria names the
  // side it chose on the popover itself: waiting for "top" waits for the flip.
  const popover = list.locator("..");
  await expect(popover).toHaveAttribute("data-placement", "top");
  await atRest(page);
  const { field: fieldBox, popover: popoverBox, view } = await settledBoxes(page);
  expect(fieldBox.y! + fieldBox.height! + 160, "the field sits low enough that the list cannot open below").toBeGreaterThan(view);
  expect(popoverBox.y! + popoverBox.height!, "list above the field").toBeLessThanOrEqual(fieldBox.y! + 0.5);
  await visible(page, popover, "list");
  await visible(page, page.getByRole("option").first(), "first match");
});

test("on a short viewport the sheet comes from the top edge it sits at, not from the bottom", async ({ page }) => {
  await page.goto("/harness/overlays.html?open=sheet");
  const panel = page.locator(".sheet-panel");
  await expect(panel).toBeVisible();
  await expect(page.locator("[data-entering]")).toHaveCount(0);
  // The enter state, held still: where would the panel start from?
  const start = await panel.evaluate((element: HTMLElement) => {
    element.style.transition = "none";
    element.setAttribute("data-entering", "");
    const style = getComputedStyle(element);
    return { translate: style.translate, opacity: style.opacity, scale: style.scale, top: element.getBoundingClientRect().top };
  });
  if (test.info().project.name === "short-wide-chromium") {
    // From 640 px the sheet is a centred panel: it fades and grows a little.
    expect(start.translate).toBe("none");
    expect(start.opacity).toBe("0");
    expect(start.scale).toBe("0.96");
  } else {
    // Above the panel: a negative vertical offset of its own height.
    const [, y] = start.translate.split(" ");
    expect(y, start.translate).toBe("-100%");
  }
});

test("the list of a combo box lifts off the page with a shadow", async ({ page }) => {
  await page.goto("/harness/overlays.html?open=dialog");
  const field = page.getByRole("combobox", { name: "Drucker" });
  await field.click();
  await field.fill("P");
  const popover = page.getByRole("listbox").locator("..");
  await expect(popover).toBeVisible();
  const shadow = await popover.evaluate((element) => getComputedStyle(element).boxShadow);
  expect(shadow).not.toBe("none");
});
