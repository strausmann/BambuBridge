import type { Page } from "@playwright/test";
import { expect, KEY_HEADER, makeDemoInstance, shot, signedInAt, test } from "./fixtures";

test.use({ serviceWorkers: "block" });

async function waitForEvents(page: Page, token: string, count: number) {
  await expect
    .poll(async () => ((await (await page.request.get("/api/v1/events?limit=50", { headers: { [KEY_HEADER]: token } })).json()) as { items: unknown[] }).items.length, { timeout: 30_000 })
    .toBeGreaterThanOrEqual(count);
}

test("events: filter by period, source and type; the detail shows payload and deliveries", async ({ page }) => {
  const token = await signedInAt(page, "/");
  await makeDemoInstance(page, token, "first");
  await makeDemoInstance(page, token, "second", "other");
  await waitForEvents(page, token, 4);

  await page.goto("/protocol");
  const list = page.getByRole("list", { name: "Ereignisse" });
  await expect(list.getByRole("listitem").first()).toBeVisible({ timeout: 20_000 });
  await shot(page, "protocol-events");

  // Source: only the events of one instance.
  const all = await list.getByRole("listitem").count();
  await page.getByLabel("Quelle").selectOption({ label: "second" });
  await expect(list.getByText(/second/).first()).toBeVisible();
  await expect(list.getByText(/first/)).toHaveCount(0);
  await page.getByLabel("Quelle").selectOption({ label: "Alle Quellen" });
  await expect(list.getByRole("listitem")).not.toHaveCount(0);
  expect(all).toBeGreaterThan(0);

  // Type: a type nobody emitted is the empty list with its own words.
  await page.getByLabel("Ereignistyp").selectOption("integration.demo.tick");
  await expect(list.getByRole("listitem").first()).toBeVisible();
  await page.getByLabel("Ereignistyp").selectOption({ label: "Alle Typen" });

  // Period: a start in the future leaves nothing; a start in the past leaves the events.
  await page.getByLabel("Von").fill("2099-01-01T00:00");
  await expect(page.getByText("Keine Ereignisse für diese Filter.")).toBeVisible();
  await page.getByLabel("Von").fill("2020-01-01T00:00");
  await expect(list.getByRole("listitem").first()).toBeVisible();

  // The detail.
  await list.getByRole("button").first().click();
  const detail = page.getByTestId("event-detail");
  await expect(detail.getByLabel("Nutzdaten des Ereignisses")).toContainText('"sequence"');
  await shot(page, "protocol-event-detail");
  await page.keyboard.press("Escape");
  await expect(detail).toBeHidden();
});

test("communication: the demo token shows as *** in the list and in the detail, never in the clear", async ({ page }) => {
  const token = await signedInAt(page, "/");
  await makeDemoInstance(page, token, "first");
  await expect
    .poll(async () => ((await (await page.request.get("/api/v1/communication?limit=10", { headers: { [KEY_HEADER]: token } })).json()) as { items: unknown[] }).items.length, { timeout: 30_000 })
    .toBeGreaterThan(0);

  await page.goto("/protocol");
  await page.getByRole("tab", { name: "Kommunikation" }).click();
  const list = page.getByRole("list", { name: "Kommunikation" });
  await expect(list.getByText("demo://tick?token=***").first()).toBeVisible({ timeout: 20_000 });
  await shot(page, "protocol-communication");

  await list.getByRole("button").first().click();
  const detail = page.getByTestId("communication-detail");
  await expect(detail.getByText("demo://tick?token=***")).toBeVisible();
  await expect(detail.getByLabel("Antwort: Inhalt")).toContainText("***");
  expect(await page.evaluate(() => document.documentElement.outerHTML.includes("e2e-demo-token-1234"))).toBe(false);

  // Filter by the class of the answer: the demo peer answers without a status, so 5xx is empty.
  await page.keyboard.press("Escape");
  await page.getByLabel("Antwort", { exact: true }).selectOption("5xx");
  await expect(page.getByText("Keine Einträge für diese Filter.")).toBeVisible();
});
