import { expect, KEY_HEADER, shot, signedInAt, test } from "./fixtures";

// The management pages, end to end against the real backend: acceptance 2 of the plan.
test.use({ serviceWorkers: "block" });

interface EventsAnswer {
  items: { type: string; payload: { label?: string; sequence?: number } }[];
}

test("a demo instance: made, tested, saved, seen in the overview and the protocol, changed without a restart", async ({ page }) => {
  const token = await signedInAt(page, "/providers");
  await expect(page.getByText(/Es gibt noch keine Instanz/)).toBeVisible();
  await shot(page, "providers-empty");

  // Make it: type picked, secret typed, tested with the unsaved values, saved.
  await page.getByRole("button", { name: "Instanz hinzufügen" }).click();
  const sheet = page.getByRole("dialog");
  await sheet.getByRole("combobox", { name: "Typ" }).click();
  await page.getByRole("option", { name: "demo (integration)" }).click();
  await sheet.getByRole("textbox", { name: "Name" }).fill("demo");
  await sheet.getByRole("spinbutton", { name: /Interval/ }).fill("1");
  await sheet.getByLabel(/^Token/).fill("e2e-demo-token-1234");
  await expect(sheet.getByTestId("secret-state-token")).toHaveText("nicht gesetzt");
  await shot(page, "provider-form");
  await sheet.getByRole("button", { name: "Verbindung testen" }).click();
  await expect(sheet.getByTestId("probe-result")).toContainText("Verbindung in Ordnung");
  await sheet.getByRole("button", { name: "Speichern" }).click();
  await expect(sheet).toBeHidden();

  // The instance is there and, once the server started it, connected. The secret is only "set".
  const card = page.getByRole("article", { name: "demo", exact: true });
  await expect(card).toBeVisible();
  await expect(card.getByText("Verbunden")).toBeVisible({ timeout: 15_000 });
  await shot(page, "providers-list");
  expect(await page.evaluate(() => document.documentElement.outerHTML.includes("e2e-demo-token-1234"))).toBe(false);

  // The first tick lands in the overview and in the protocol.
  await page.getByRole("link", { name: "Übersicht" }).filter({ visible: true }).first().click();
  const recent = page.getByRole("region", { name: "Letzte Ereignisse" });
  await expect(recent.getByText("integration.demo.tick").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("region", { name: "Instanzen" }).getByText("Verbunden")).toBeVisible();
  await shot(page, "overview");
  await page.goto("/protocol");
  const list = page.getByRole("list", { name: "Ereignisse" });
  await expect(list.getByText("integration.demo.tick").first()).toBeVisible({ timeout: 20_000 });

  // Change interval and label: new events carry the new label, and nothing was restarted.
  await page.goto("/providers");
  await page.getByRole("article", { name: "demo", exact: true }).getByRole("button", { name: "Bearbeiten" }).click();
  const edit = page.getByRole("dialog");
  await expect(edit.getByTestId("secret-state-token")).toHaveText("gesetzt");
  await edit.getByRole("textbox", { name: "Label" }).fill("beta");
  await edit.getByRole("spinbutton", { name: /Interval/ }).fill("2");
  await edit.getByRole("button", { name: "Speichern" }).click();
  await expect(edit).toBeHidden();
  await expect
    .poll(
      async () => {
        const answer = await page.request.get("/api/v1/events?limit=20", { headers: { [KEY_HEADER]: token } });
        const events = (await answer.json()) as EventsAnswer;
        return events.items.some((event) => event.payload.label === "beta");
      },
      { message: "an event with the new label", timeout: 30_000 },
    )
    .toBe(true);

  // The action runs on the running instance and the dialog shows its result.
  await page.getByRole("button", { name: "Aktion „emit_now“" }).click();
  const run = page.getByRole("dialog");
  await run.getByRole("button", { name: "Ausführen" }).click();
  await expect(run.getByTestId("action-result")).toContainText('"sequence"');
});
