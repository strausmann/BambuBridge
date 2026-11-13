import { BASE_URL } from "./env";
import { expect, signedInAt, test, waitForWorker } from "./fixtures";

test("paths the server owns reach the server under any spelling, never the worker's shell", async ({ page, context }) => {
  await signedInAt(page, "/");
  await waitForWorker(page);
  // A second tab of the same origin, controlled by the same worker. Its answers are JSON or
  // text, which WebKit shows in a viewer with inline styles the CSP refuses; that is the
  // browser's viewer, not the app, so this tab is not watched by the CSP guard.
  const tab = await context.newPage();

  // Spellings the server maps to its own paths (it decodes, it ignores the query).
  const cases: [string, RegExp][] = [
    ["/%61pi/v1/info", /"version"/],
    ["/a%70i/v1/info", /"version"/],
    ["/api/v1/info?x=1", /"version"/],
    ["/healthz?x", /ok/i],
    ["/openapi.json?x", /"openapi"/],
  ];
  for (const [path, body] of cases) {
    const response = await tab.goto(`${BASE_URL}${path}`);
    expect(response, path).not.toBeNull();
    expect(response!.fromServiceWorker(), path).toBe(false);
    expect(await tab.locator("body").innerText(), path).toMatch(body);
  }
  // The tab is under the worker's control: the shell it would have answered with is there.
  await tab.goto(`${BASE_URL}/device`);
  expect(await tab.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);
});
