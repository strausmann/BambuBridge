import { expect, shot, signedInAt, test } from "./fixtures";

test("Back closes an open sheet and stays on the page; the next Back leaves as before", async ({ page }) => {
  await signedInAt(page, "/settings");
  await page.getByRole("link", { name: /Dieses Gerät/ }).click();
  await expect(page).toHaveURL(/\/device$/);

  await page.getByRole("button", { name: "Als App installieren" }).click();
  const sheet = page.getByRole("dialog", { name: "Als App installieren" });
  await expect(sheet).toBeVisible();
  await shot(page, "device-install-sheet", { fullPage: false });

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
