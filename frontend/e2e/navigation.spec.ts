import { PARAMETER_ROUTES, SHELL_PAGES } from "../src/app/routes";
import { expect, openMain, signedInAt, test } from "./fixtures";

const HEADINGS: Record<(typeof SHELL_PAGES)[number], string> = {
  "/": "Übersicht",
  "/providers": "Anbieter",
  "/protocol": "Protokoll",
  "/settings": "Einstellungen",
  "/device": "Dieses Gerät",
};

/** The main destinations of the tab bar; every other page is listed on the settings page. */
const TABS: Record<string, string> = { "/": "Übersicht", "/providers": "Anbieter", "/protocol": "Protokoll", "/settings": "Einstellungen" };

test("every page of the app is reached by tapping, without a sidebar and without typing an address", async ({ page }) => {
  // Routes with a parameter have no page yet (the settings sections arrive later); when they do,
  // this list makes the test name them here.
  expect(PARAMETER_ROUTES).toEqual(["/settings/$section"]);
  await signedInAt(page, "/");
  await expect(page.getByRole("complementary")).toBeHidden();

  for (const path of SHELL_PAGES) {
    await openMain(page, "Übersicht");
    if (path in TABS) {
      await openMain(page, TABS[path]!);
    } else {
      await openMain(page, "Einstellungen");
      await page.getByRole("navigation", { name: "Einstellungsseiten" }).locator(`a[href="${path}"]`).tap();
    }
    await expect(page, path).toHaveURL(new RegExp(`${path.replace(/\//g, "\\/")}$`));
    await expect(page.getByRole("heading", { level: 1, name: HEADINGS[path] })).toBeVisible();
  }
});
