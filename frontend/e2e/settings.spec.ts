import { expect, KEY_HEADER, shot, signedInAt, test } from "./fixtures";

test.use({ serviceWorkers: "block" });

test("access: a new token is shown once, signs in, and is revoked", async ({ page, request }) => {
  await signedInAt(page, "/settings/access");
  await page.getByRole("button", { name: "Token anlegen" }).click();
  const sheet = page.getByRole("dialog");
  await sheet.getByRole("textbox", { name: "Name" }).fill("reader");
  await sheet.getByLabel("Berechtigung").selectOption("read");
  await sheet.getByRole("button", { name: "Anlegen" }).click();

  const shown = page.getByTestId("new-token");
  await expect(shown).toBeVisible();
  const plaintext = (await shown.textContent())!.trim();
  expect(plaintext.length).toBeGreaterThan(20);
  await shot(page, "token-shown");
  await page.getByRole("button", { name: "Fertig" }).click();
  await expect(shown).toBeHidden();

  // Once: it is nowhere in the page, the list shows the start only.
  expect(await page.evaluate((value) => document.documentElement.outerHTML.includes(value), plaintext)).toBe(false);
  const card = page.getByRole("article", { name: "reader" });
  await expect(card).toContainText(plaintext.slice(0, 11));
  await shot(page, "access");

  // It works, within its scope.
  const readable = await request.get("/api/v1/providers", { headers: { [KEY_HEADER]: plaintext } });
  expect(readable.status()).toBe(200);
  const refused = await request.get("/api/v1/admin/api-keys", { headers: { [KEY_HEADER]: plaintext } });
  expect(refused.status()).toBe(403);

  // Revoke it: asked first, then it is refused.
  await card.getByRole("button", { name: "Entziehen" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Endgültig entziehen" }).click();
  await expect(card).toBeHidden();
  const gone = await request.get("/api/v1/providers", { headers: { [KEY_HEADER]: plaintext } });
  expect(gone.status()).toBe(401);
});

test("single sign-on: the header can be changed and the trust token is write-only", async ({ page }) => {
  const token = await signedInAt(page, "/settings/sso");
  const header = page.getByRole("combobox", { name: "Kopfzeile mit dem Benutzernamen" });
  await expect(header).toBeVisible();
  const options = await header.locator("option").allTextContents();
  const other = options.find((option) => option !== "Remote-User");
  test.skip(!other, "the server offers only one user header");
  await header.selectOption(other!);
  await page.getByLabel("Vertrauens-Token (leer schaltet SSO aus)").fill("t".repeat(40));
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("status").filter({ hasText: "ohne Neustart" })).toBeVisible();
  await shot(page, "sso");

  // After a reload the header is the new one and the token is only "set".
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Kopfzeile mit dem Benutzernamen" })).toHaveValue(other!);
  await expect(page.getByTestId("secret-state-sso.trust_token")).toHaveText("gesetzt");
  expect(await page.evaluate(() => document.documentElement.outerHTML.includes("tttttttttt"))).toBe(false);
  const settings = await page.request.get("/api/v1/settings", { headers: { [KEY_HEADER]: token } });
  const trust = ((await settings.json()) as { key: string; value: unknown }[]).find((s) => s.key === "sso.trust_token");
  expect(trust?.value).toBeNull();
});

test("retention: the days can be changed and stay changed", async ({ page }) => {
  const token = await signedInAt(page, "/settings/retention");
  const days = page.getByRole("spinbutton", { name: "Ereignisse aufbewahren (Tage)" });
  await expect(days).toHaveValue("90");
  await days.fill("14");
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("status").filter({ hasText: "ohne Neustart" })).toBeVisible();
  await shot(page, "retention");

  await page.reload();
  await expect(page.getByRole("spinbutton", { name: "Ereignisse aufbewahren (Tage)" })).toHaveValue("14");
  const settings = await page.request.get("/api/v1/settings", { headers: { [KEY_HEADER]: token } });
  const stored = ((await settings.json()) as { key: string; value: unknown }[]).find((s) => s.key === "retention.events_days");
  expect(stored?.value).toBe(14);

  // Back to the default.
  await page.getByRole("button", { name: /auf Standard zurücksetzen/ }).first().click();
  await page.getByRole("button", { name: "Speichern" }).click();
  await expect(page.getByRole("status").filter({ hasText: "ohne Neustart" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("spinbutton", { name: "Ereignisse aufbewahren (Tage)" })).toHaveValue("90");
});

test("system and general pages are reached from the settings list", async ({ page }) => {
  await signedInAt(page, "/settings");
  await page.getByRole("navigation", { name: "Einstellungsseiten" }).getByRole("link", { name: /System/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "System" })).toBeVisible();
  await expect(page.getByTestId("server-version")).toBeVisible();
  await page.goto("/settings");
  await page.getByRole("navigation", { name: "Einstellungsseiten" }).getByRole("link", { name: /Allgemein/ }).click();
  await expect(page.getByRole("spinbutton", { name: /Zeitfenster/ })).toHaveValue("600");
});
