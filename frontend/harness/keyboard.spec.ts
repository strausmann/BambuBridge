import { expect, test, type Locator, type Page } from "@playwright/test";

/** Inside the visible part of the page (the visual viewport: above the on-screen keyboard). */
async function visible(page: Page, locator: Locator, what: string): Promise<void> {
  // Measured once the enter animations are over, not on their way in.
  await expect(page.locator("[data-entering]")).toHaveCount(0);
  await page.waitForFunction(() => document.getAnimations().every((animation) => animation.playState !== "running"));
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
      await page.screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/phone-sheet-keyboard.png` });
    }
  });
}

test("the list flips above the field when there is no room below it", async ({ page }) => {
  await page.goto("/harness/overlays.html?open=sheet&low=1");
  const field = page.getByRole("combobox", { name: "Drucker" });
  // Scroll the content to its end: the field now sits at the bottom of the visible part.
  await page.getByRole("dialog").evaluate((dialog) => {
    const body = dialog.querySelector(".overflow-y-auto")!;
    body.scrollTop = body.scrollHeight;
  });
  await field.click();
  const list = page.getByRole("listbox");
  await expect(list).toBeVisible();
  // The popover (the list's scrolling frame) is what can be seen of the list.
  const popover = list.locator("..");
  await visible(page, popover, "list");
  const fieldBox = (await field.boundingBox())!;
  const popoverBox = (await popover.boundingBox())!;
  const view = await page.evaluate(() => window.visualViewport!.height);
  expect(fieldBox.y + fieldBox.height + 160, "the field sits low enough that the list cannot open below").toBeGreaterThan(view);
  expect(popoverBox.y + popoverBox.height, "list above the field").toBeLessThanOrEqual(fieldBox.y + 0.5);
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
