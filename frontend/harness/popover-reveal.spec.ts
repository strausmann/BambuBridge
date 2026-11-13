import { expect, test, type Page } from "@playwright/test";

// A touch device reveals a popover that just opened only after two animation frames, and after a text
// field took the focus (as the combo box's input does) only once the on-screen keyboard has moved, up
// to 600 ms later. A close inside that window used to leave the list stuck half-way out
// (data-exiting) over the page: the late reveal cancelled the exit transitions it waited for.
// The frames are held back here, so the close deterministically comes before the reveal.
//
// The time is held back with them: React Aria expects a keyboard only for 600 ms after a text field
// took the focus (`supportsKeyboard` in react-aria's keyboard.ts compares performance.now() with the
// moment of the focus) and reveals at once after that. On a slow machine the list is mounted later
// than that - looped under 4x CPU throttling this test failed once in 90 runs for exactly this reason
// (the list was not hidden when it was looked at). With a frozen clock the list is mounted "right
// after the focus" however long that really takes.

type Frames = { __frames: { hold: boolean; freeze: () => void; release: () => void } };

test.beforeEach(async ({ page, hasTouch }) => {
  // A phone reports touch points; Playwright's WebKit does not, even with touch enabled.
  if (hasTouch) {
    await page.addInitScript(() => {
      if (navigator.maxTouchPoints === 0) Object.defineProperty(Navigator.prototype, "maxTouchPoints", { get: () => 5 });
    });
  }
  await page.addInitScript(() => {
    const frames = { hold: false, queue: [] as FrameRequestCallback[] };
    const realNow = performance.now.bind(performance);
    let frozenAt: number | null = null;
    performance.now = () => frozenAt ?? realNow();
    (window as unknown as Frames).__frames = Object.assign(frames, {
      freeze: () => {
        frames.hold = true;
        frozenAt = realNow();
      },
      release: () => {
        frames.hold = false;
        frozenAt = null;
        for (const callback of frames.queue.splice(0)) originalFrame(callback);
      },
    });
    const originalFrame = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (callback) => (frames.hold ? (frames.queue.push(callback), 0) : originalFrame(callback));
  });
});

/** The page with the combo box alone; animation frames and the clock are held back from now on. */
async function holdFrames(page: Page): Promise<void> {
  await page.goto("/harness/overlays.html?open=combo");
  // The exit transition (150 ms) must still be running when the frames are released, however slow the
  // machine: a longer one makes the window independent of the speed of this test.
  await page.addStyleTag({ content: ".popover-panel { transition-duration: 1s !important; }" });
  await expect(page.getByRole("combobox", { name: "Drucker" })).toBeVisible();
  await page.evaluate(() => (window as unknown as Frames).__frames.freeze());
}

test("a list closed before it was revealed is gone and stays gone", async ({ page }) => {
  await holdFrames(page);
  const field = page.getByRole("combobox", { name: "Drucker" });
  await field.tap();
  const list = page.getByRole("listbox");
  await expect(list).toBeAttached();
  // The window this test is about: the list is still hidden, waiting for its frames.
  expect(await list.locator("..").evaluate((popover) => (popover as HTMLElement).style.clipPath)).toBe("inset(50%)");

  await page.keyboard.press("Escape");
  await page.evaluate(() => (window as unknown as Frames).__frames.release());
  await expect(list).toHaveCount(0);
  await expect(page.locator("[data-exiting]")).toHaveCount(0);
});

test("opened again after such a close, the list is revealed and usable", async ({ page }) => {
  await holdFrames(page);
  const field = page.getByRole("combobox", { name: "Drucker" });
  await field.tap();
  await expect(page.getByRole("listbox")).toBeAttached();
  await page.keyboard.press("Escape");
  await page.evaluate(() => (window as unknown as Frames).__frames.release());
  await expect(page.getByRole("listbox")).toHaveCount(0);

  await page.keyboard.press("ArrowDown");
  const first = page.getByRole("option").first();
  await expect(first).toBeVisible();
  await expect(page.locator("[data-entering]")).toHaveCount(0);
  await page.keyboard.press("Enter");
  await expect(field).toHaveValue("X1 Carbon Werkstatt");
});

test("a revealed list leaves with its exit animation, then it is gone", async ({ page }) => {
  await page.goto("/harness/overlays.html?open=combo");
  const field = page.getByRole("combobox", { name: "Drucker" });
  await field.tap();
  const first = page.getByRole("option").first();
  await expect(first).toBeVisible();
  await expect(page.locator("[data-entering]")).toHaveCount(0);

  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
});
