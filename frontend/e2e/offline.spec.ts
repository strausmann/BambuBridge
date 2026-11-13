import { expect, shot, signedInAt, test, waitForWorker } from "./fixtures";

test("without a connection: the shell still opens, says so, and shows no old data", async ({ page, context }) => {
  await signedInAt(page, "/");
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  await waitForWorker(page);

  await context.setOffline(true);
  const banner = page.getByRole("status").filter({ hasText: "Keine Verbindung" });
  await expect(banner).toBeVisible();

  // A reload while offline: the worker serves the shell, the API is not answered from any cache.
  await page.reload();
  await expect(banner).toBeVisible();
  await expect(page.getByRole("heading", { name: "Der Server ist nicht erreichbar." })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("signed-in-user")).toHaveCount(0);
  await shot(page, "offline-banner", { fullPage: false });

  await context.setOffline(false);
  await expect(banner).toHaveCount(0);
  await page.getByRole("button", { name: "Erneut versuchen" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
});
