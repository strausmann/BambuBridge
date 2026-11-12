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
