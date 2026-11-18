import { expect, test, type Page } from "@playwright/test";

const SIGNED_IN = "/harness/shell.html?state=signed-in";
const SIGN_IN = "/harness/shell.html";

/** Controls a finger has to hit: at least 44 x 44 CSS pixels. */
async function smallTargets(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>('button, a[href], [role="radio"], input')]
      .filter((element) => {
        const box = element.getBoundingClientRect();
        // Hidden elements and the skip link (visible only on keyboard focus) have no touch target.
        if (box.width <= 1 || box.height <= 1 || getComputedStyle(element).visibility === "hidden") return false;
        const target = element.matches("input[type=radio]") ? element.closest("label")!.getBoundingClientRect() : box;
        return target.width < 44 || target.height < 44;
      })
      .map((element) => `${element.tagName} "${(element.getAttribute("aria-label") ?? element.textContent ?? "").trim()}"`),
  );
}

async function overflowsSideways(page: Page): Promise<boolean> {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
}

test.describe("desktop (1280 px)", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("shows the sidebar, hides the tab bar", async ({ page }) => {
    await page.goto(SIGNED_IN);
    await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
    await expect(page.locator("aside")).toBeVisible();
    await expect(page.locator("[data-tabbar]")).toBeHidden();
    // The content starts to the right of the sidebar and below the top bar.
    const sidebar = (await page.locator("aside").boundingBox())!;
    const heading = (await page.getByRole("heading", { name: "Übersicht" }).boundingBox())!;
    const header = (await page.locator("header").boundingBox())!;
    expect(heading.x).toBeGreaterThanOrEqual(sidebar.x + sidebar.width);
    expect(heading.y).toBeGreaterThanOrEqual(header.y + header.height);
  });

  test("the theme thumb sits exactly under the chosen option", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(SIGNED_IN);
    const group = page.getByRole("radiogroup", { name: "Design" });
    for (const name of ["Dunkles Design", "Helles Design", "Systemdesign"]) {
      await group.getByRole("radio", { name }).click({ force: true });
      await expect(group.getByRole("radio", { name })).toBeChecked();
      await expect
        .poll(async () => {
          const thumb = (await group.locator("span[aria-hidden]").first().boundingBox())!;
          const option = (await group.locator("label").filter({ has: page.getByRole("radio", { name }) }).boundingBox())!;
          return Math.abs(thumb.x - option.x) + Math.abs(thumb.y - option.y);
        })
        .toBeLessThan(1);
    }
  });

  test("the theme changes the page colours to the dark tokens and back", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
    await page.goto(SIGNED_IN);
    await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
    const background = () => page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor);
    await expect.poll(background).toBe("rgb(243, 247, 251)");
    await page.getByRole("radio", { name: "Dunkles Design" }).click({ force: true });
    await expect.poll(background).toBe("rgb(13, 18, 24)");
    // The logo swaps to its dark drawing.
    await expect(page.locator('aside [data-logo="lockup"] .logo-dark')).toBeVisible();
    await expect(page.locator('aside [data-logo="lockup"] .logo-light')).toBeHidden();
    await page.getByRole("radio", { name: "Helles Design" }).click({ force: true });
    await expect.poll(background).toBe("rgb(243, 247, 251)");
  });

  test("follows a dark system setting until a theme is chosen", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto(SIGN_IN);
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor)).toBe("rgb(13, 18, 24)");
  });

  test("text is set in the self-hosted fonts, and the font files were fetched from this origin", async ({ page }) => {
    await page.goto(SIGN_IN);
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    const families = await page.evaluate(() => ({
      heading: getComputedStyle(document.querySelector("h1")!).fontFamily,
      text: getComputedStyle(document.body).fontFamily,
      field: getComputedStyle(document.querySelector("input")!).fontFamily,
    }));
    expect(families.heading).toMatch(/^"?Space Grotesk Variable/);
    expect(families.text).toMatch(/^"?Inter Variable/);
    expect(families.field).toMatch(/^"?JetBrains Mono Variable/);
    // `document.fonts.check` answers yes through a system fallback too; the fetched files are the proof.
    const fetched = await page.evaluate(() => performance.getEntriesByType("resource").map((entry) => entry.name).filter((name) => name.includes(".woff2")));
    expect(fetched.some((name) => name.includes("inter-latin-wght-normal"))).toBe(true);
    expect(fetched.some((name) => name.includes("space-grotesk-latin-wght-normal"))).toBe(true);
    for (const name of fetched) expect(new URL(name).origin).toBe(new URL(page.url()).origin);
  });
});

test.describe("phone (375 x 780)", () => {
  test.use({ viewport: { width: 375, height: 780 }, hasTouch: true });

  test("shows the tab bar at the bottom edge, hides the sidebar", async ({ page }) => {
    await page.goto(SIGNED_IN);
    await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
    await expect(page.locator("aside")).toBeHidden();
    const bar = (await page.locator("[data-tabbar]").boundingBox())!;
    expect(Math.round(bar.y + bar.height)).toBe(780);
    expect(bar.width).toBe(375);
    expect(await overflowsSideways(page)).toBe(false);
  });

  test("every control is a full touch target, in the shell and on the sign-in", async ({ page }) => {
    await page.goto(SIGNED_IN);
    await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
    expect(await smallTargets(page)).toEqual([]);
    await page.goto(SIGN_IN);
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    expect(await smallTargets(page)).toEqual([]);
    await page.goto(`${SIGN_IN}?path=/bootstrap`);
    await expect(page.getByRole("heading", { name: "Erstes Admin-Token anlegen" })).toBeVisible();
    expect(await smallTargets(page)).toEqual([]);
  });

  test("fields are at least 16 px, so iOS does not zoom into them", async ({ page }) => {
    await page.goto(SIGN_IN);
    const size = await page.getByLabel("API-Token").evaluate((input) => parseFloat(getComputedStyle(input).fontSize));
    expect(size).toBeGreaterThanOrEqual(16);
  });

  test("the last line of a page stays clear of the tab bar", async ({ page }) => {
    await page.goto(SIGNED_IN);
    const main = page.locator("main#content");
    await expect(main).toBeVisible();
    const padding = await main.evaluate((element) => parseFloat(getComputedStyle(element).paddingBottom));
    const bar = (await page.locator("[data-tabbar]").boundingBox())!;
    expect(padding).toBeGreaterThanOrEqual(bar.height);
  });

  test("a very long user name does not push the controls out of the top bar", async ({ page }) => {
    await page.setViewportSize({ width: 700, height: 780 });
    await page.goto(SIGNED_IN);
    await expect(page.getByTestId("signed-in-user")).toBeVisible();
    const signOut = (await page.getByRole("button", { name: "Abmelden" }).boundingBox())!;
    expect(signOut.x + signOut.width).toBeLessThanOrEqual(700);
    expect(await overflowsSideways(page)).toBe(false);
  });
});

test.describe("narrow and short viewports", () => {
  test("nothing overflows sideways at 320 px", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    for (const url of [SIGNED_IN, SIGN_IN, `${SIGN_IN}?path=/bootstrap`]) {
      await page.goto(url);
      await expect(page.locator("h1")).toBeVisible();
      expect(await overflowsSideways(page), url).toBe(false);
    }
  });

  test("the new admin token is fully visible at 320 px, without scrolling inside its field", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    await page.goto(`${SIGN_IN}?path=/bootstrap`);
    await page.getByLabel("Bootstrap-Schlüssel").fill("harness");
    await page.getByRole("button", { name: "Admin-Token anlegen" }).click();
    const shown = page.getByTestId("admin-token");
    await expect(shown).toHaveText(/^bb_pat_Harness.*0123456789$/);
    // Nothing of it is cut off or scrolled out of its box.
    expect(await shown.evaluate((box) => box.scrollHeight <= box.clientHeight && box.scrollWidth <= box.clientWidth)).toBe(true);
    expect(await overflowsSideways(page)).toBe(false);
    expect(await smallTargets(page)).toEqual([]);
  });

  test("with the on-screen keyboard open (390 x 400) the sign-in sits at the top and its button is reachable", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 400 });
    await page.goto(SIGN_IN);
    const field = page.getByLabel("API-Token");
    await field.focus();
    // Top-aligned: the panel is not centred into a strip above and below the fold.
    const logo = (await page.locator('[data-logo="lockup"]').boundingBox())!;
    expect(logo.y).toBeLessThan(40);
    // The page scrolls, so the field and the button under it can both be brought into view.
    const submit = page.getByRole("button", { name: "Anmelden" });
    await submit.scrollIntoViewIfNeeded();
    await expect(submit).toBeInViewport({ ratio: 1 });
    await expect(field).toBeInViewport({ ratio: 1 });
  });
});

/** Distance in px between the text of a control and the control's own border box, smallest side. */
async function labelInset(page: Page, name: string): Promise<number> {
  return page.getByRole("button", { name }).evaluate((button) => {
    const range = document.createRange();
    range.selectNodeContents(button);
    const text = range.getBoundingClientRect();
    const box = button.getBoundingClientRect();
    return Math.min(text.left - box.left, box.right - text.right, text.top - box.top, box.bottom - text.bottom);
  });
}

test.describe("fix round 3", () => {
  test("the waiting mark stays inside the button when the two-line label fills its line (320 px)", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 780 });
    await page.goto(`${SIGN_IN}?slow=1`);
    const button = page.getByRole("button", { name: "Mit einmaliger Anmeldung (SSO) fortfahren" });
    const label = button.locator("span.relative");
    const before = await label.boundingBox();
    await button.click();
    const mark = button.getByTestId("busy-mark");
    await expect(mark).toBeVisible();
    const [outer, inner, after] = [await button.boundingBox(), await mark.boundingBox(), await label.boundingBox()];
    expect(inner!.x).toBeGreaterThanOrEqual(outer!.x);
    expect(inner!.x + inner!.width).toBeLessThanOrEqual(outer!.x + outer!.width);
    expect(inner!.y).toBeGreaterThanOrEqual(outer!.y);
    expect(inner!.y + inner!.height).toBeLessThanOrEqual(outer!.y + outer!.height);
    // The room for the mark is not taken from the label: it still fits on two lines.
    const lineHeight = await label.evaluate((element) => parseFloat(getComputedStyle(element).lineHeight));
    expect(Math.round(before!.height / lineHeight)).toBe(2);
    // The label does not move when the mark appears.
    expect(after).toEqual(before);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const shots = process.env.E2E_SCREENSHOT_DIR;
    if (shots && test.info().project.name === "chromium") await page.screenshot({ path: `${shots}/phone-sign-in-waiting.png` });
  });
});

test.describe("fix round 1", () => {
  for (const width of [320, 375]) {
    test(`the single sign-on label keeps clear of the button's border at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 780 });
      await page.goto(SIGN_IN);
      const name = "Mit einmaliger Anmeldung (SSO) fortfahren";
      await expect(page.getByRole("button", { name })).toBeVisible();
      expect(await labelInset(page, name)).toBeGreaterThanOrEqual(8);
      expect(await page.getByRole("button", { name }).evaluate((b) => b.scrollHeight <= b.clientHeight && b.scrollWidth <= b.clientWidth)).toBe(true);
      expect(await smallTargets(page)).toEqual([]);
    });
  }

  test("a long press on a navigation entry selects no text and opens no link callout", async ({ page }) => {
    const unselectable = () =>
      page.evaluate(() =>
        [...document.querySelectorAll<HTMLElement>("nav a")]
          .filter((link) => link.getBoundingClientRect().width > 0)
          .map((link) => {
            const style = getComputedStyle(link);
            return style.userSelect === "none" || style.webkitUserSelect === "none";
          }),
      );
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(SIGNED_IN);
    await expect(page.locator("aside")).toBeVisible();
    expect(await unselectable()).toEqual([true, true, true, true]);
    await page.setViewportSize({ width: 375, height: 780 });
    await expect(page.locator("[data-tabbar]")).toBeVisible();
    expect(await unselectable()).toEqual([true, true, true, true]);
  });

  test("iOS: a tall layout viewport with a short visual viewport still puts the sign-in at the top", async ({ page }) => {
    // iOS Safari keeps the layout viewport when the keyboard opens; only window.visualViewport shrinks.
    await page.addInitScript(() => {
      const fake = Object.assign(new EventTarget(), { height: 320, width: 390, offsetTop: 0, offsetLeft: 0, pageTop: 0, pageLeft: 0, scale: 1 });
      Object.defineProperty(window, "visualViewport", { value: fake, configurable: true });
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(SIGN_IN);
    await expect(page.locator("main[data-short]")).toBeVisible();
    const logo = (await page.locator('[data-logo="lockup"]').boundingBox())!;
    expect(logo.y).toBeLessThan(40);
  });

  test("without the keyboard the same phone centres the sign-in", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(SIGN_IN);
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    await expect(page.locator("main[data-short]")).toHaveCount(0);
    const logo = (await page.locator('[data-logo="lockup"]').boundingBox())!;
    expect(logo.y).toBeGreaterThan(40);
  });

  test("a failed sign-out keeps the shell and shows the message inside the phone's width", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 780 });
    await page.goto(`${SIGNED_IN}&signout=fail`);
    await page.getByRole("button", { name: "Abmelden" }).click();
    const alert = page.getByRole("alert").filter({ hasText: "Abmelden fehlgeschlagen" });
    await expect(alert).toHaveText("Abmelden fehlgeschlagen, die Sitzung ist noch offen");
    await expect(alert).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
    // It sits between the content's heading and the tab bar and covers neither.
    const box = (await alert.boundingBox())!;
    const heading = (await page.getByRole("heading", { name: "Übersicht" }).boundingBox())!;
    const bar = (await page.locator("[data-tabbar]").boundingBox())!;
    expect(box.y).toBeGreaterThan(heading.y + heading.height);
    expect(box.y + box.height).toBeLessThanOrEqual(bar.y);
    expect(await overflowsSideways(page)).toBe(false);
    expect(await smallTargets(page)).toEqual([]);
    const shots = process.env.E2E_SCREENSHOT_DIR;
    if (shots && test.info().project.name === "chromium") await page.screenshot({ path: `${shots}/phone-sign-out-failed.png` });
    await page.getByRole("button", { name: "Meldung schließen" }).click();
    await expect(alert).toHaveCount(0);
  });

  test("the chosen theme option has a visible ring", async ({ page }) => {
    await page.goto(SIGN_IN);
    const thumb = page.getByRole("radiogroup", { name: "Design" }).locator("span[aria-hidden]").first();
    const border = await thumb.evaluate((element) => {
      const style = getComputedStyle(element);
      return { width: parseFloat(style.borderTopWidth), colour: style.borderTopColor, track: getComputedStyle(element.parentElement!).backgroundColor };
    });
    expect(border.width).toBeGreaterThanOrEqual(1);
    expect(border.colour).not.toBe(border.track);
  });

  test("the browser's own bars follow a chosen theme", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
    await page.goto(SIGN_IN);
    const colours = () => page.evaluate(() => [...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')].map((meta) => meta.content.toUpperCase()));
    expect(await colours()).toEqual(["#F3F7FB", "#0D1218"]);
    await page.getByRole("radio", { name: "Dunkles Design" }).click({ force: true });
    await expect.poll(colours).toEqual(["#0D1218", "#0D1218"]);
    await page.getByRole("radio", { name: "Systemdesign" }).click({ force: true });
    await expect.poll(colours).toEqual(["#F3F7FB", "#0D1218"]);
  });
});

