import { expect, shot, signedInAt, test, waitForWorker } from "./fixtures";
import { BASE_URL } from "./env";

const NEXT_BUILD = { "X-BambuBridge-E2E": "next-build" };

test("the server restarted on a new build: the open page loads the new version by itself, once", async ({ page }) => {
  await signedInAt(page, "/settings");
  await waitForWorker(page);
  await page.getByRole("link", { name: /Dieses Gerät/ }).click();
  const appBuild = page.locator("dt", { hasText: "Build dieser App" }).locator("+ dd");
  const first = (await appBuild.textContent())!.trim();
  expect(first).not.toContain("e2e-next");

  // As after a deployment: new files on the server, a new X-BambuBridge-Version.
  expect((await page.request.post(`${BASE_URL}/__e2e/next-build`, { headers: NEXT_BUILD })).status()).toBe(204);

  const loads: string[] = [];
  page.on("load", () => loads.push(page.url()));
  // The next API answer of the open page carries the new version.
  await page.getByRole("button", { name: "Erneut prüfen" }).click();

  await expect(appBuild).toContainText("e2e-next", { timeout: 20_000 });
  await expect(page).toHaveURL(/\/device$/);
  await expect(page.getByTestId("signed-in-user")).toBeAttached();
  const reloadedFor = await page.evaluate(() => JSON.parse(sessionStorage.getItem("bb.reloadedFor") ?? "[]") as string[]);
  expect(reloadedFor).toHaveLength(1);
  expect(reloadedFor[0]).toMatch(/\+e2e-next$/);
  // The new worker took over, and the page did not reload again after that.
  await page.waitForTimeout(1000);
  expect(loads).toHaveLength(1);
  await expect(page.getByRole("status").filter({ hasText: "Neue Version" })).toHaveCount(0);
});

test("a reload for this version already happened: the banner offers it instead, and its button loads the new version", async ({ page }) => {
  await signedInAt(page, "/settings");
  await waitForWorker(page);
  await page.getByRole("link", { name: /Dieses Gerät/ }).click();
  const appBuild = page.locator("dt", { hasText: "Build dieser App" }).locator("+ dd");

  expect((await page.request.post(`${BASE_URL}/__e2e/next-build`, { headers: NEXT_BUILD })).status()).toBe(204);
  const version = (await page.request.get(`${BASE_URL}/api/v1/auth/session`)).headers()["x-bambubridge-version"] ?? "";
  expect(version).toMatch(/\+e2e-next$/);
  // As if the page had already reloaded once for this version and still came up on the old build.
  await page.evaluate((v) => sessionStorage.setItem("bb.reloadedFor", JSON.stringify([v])), version);

  await page.getByRole("button", { name: "Erneut prüfen" }).click();
  const banner = page.getByRole("status").filter({ hasText: "Neue Version" });
  await expect(banner).toBeVisible();
  expect(await appBuild.textContent()).not.toContain("e2e-next");
  await shot(page, "update-banner", { fullPage: false });

  // The banner sits above the page's end: scrolled to the bottom, the last control is still
  // in view and not under the banner.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const recheck = page.getByRole("button", { name: "Erneut prüfen" });
  await expect(recheck).toBeInViewport({ ratio: 1 });
  const [control, note] = await Promise.all([recheck.boundingBox(), banner.boundingBox()]);
  expect(control!.y + control!.height, "the last control ends above the banner").toBeLessThanOrEqual(note!.y);

  await banner.getByRole("button", { name: "Neu laden" }).click();
  await expect(appBuild).toContainText("e2e-next", { timeout: 20_000 });
  await expect(page).toHaveURL(/\/device$/);
});
