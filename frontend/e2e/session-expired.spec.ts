import { RESET_HEADERS, RESET_PATH } from "./env";
import { expect, openMain, shot, signedInAt, test, waitForWorker } from "./fixtures";

test("a session revoked on the server: the next request leaves through /auth/continue and lands on the sign-in", async ({ page }) => {
  await signedInAt(page, "/protocol");
  await expect(page.getByRole("heading", { name: "Protokoll" })).toBeVisible();
  await waitForWorker(page);
  // From here on the shell comes out of the worker's cache.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Protokoll" })).toBeVisible();
  expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);

  const hops: number[] = [];
  page.on("response", (response) => {
    if (new URL(response.url()).pathname === "/auth/continue") hops.push(response.status());
  });

  // The server forgets every session (the reset empties the database).
  expect((await page.request.post(RESET_PATH, { headers: RESET_HEADERS })).status()).toBe(204);

  // The device page shows the refused sign-in path as a diagnosis and stays.
  await openMain(page, "Einstellungen");
  await page.getByRole("link", { name: /Dieses Gerät/ }).click();
  await expect(page.getByText("Erreichbar, nicht angemeldet (401)")).toBeVisible();
  await expect(page).toHaveURL(/\/device$/);
  expect(hops).toEqual([]);

  // Checking again asks the app's own session too: it finds the sign-in gone and leaves.
  await page.getByRole("button", { name: "Erneut prüfen" }).click();

  // The hop reached the server (not the worker's shell) and it answered: not signed in.
  await expect(page).toHaveURL(/\/sign-in\?redirect=%2Fdevice$/);
  await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
  await expect(page.getByLabel("API-Token")).toBeVisible();
  expect(hops).toEqual([401]);
  await shot(page, "session-expired-sign-in");
});
