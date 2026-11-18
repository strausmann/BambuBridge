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

const SECTIONS: Record<string, string> = {
  general: "Allgemein",
  access: "Zugang",
  sso: "Einmalige Anmeldung (SSO)",
  retention: "Aufbewahrung",
  system: "System",
};

test("every page of the app is reached by tapping, without a sidebar and without typing an address", async ({ page }) => {
  // A route with a parameter is reached through a page that links to it: the sections of the
  // settings (below). A new parameter route must be named here, so it is walked too.
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

  // The sections behind `/settings/$section`, each tapped from the settings list.
  for (const [section, heading] of Object.entries(SECTIONS)) {
    await openMain(page, "Einstellungen");
    await page.getByRole("navigation", { name: "Einstellungsseiten" }).locator(`a[href="/settings/${section}"]`).tap();
    await expect(page, section).toHaveURL(new RegExp(`/settings/${section}$`));
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }
});
