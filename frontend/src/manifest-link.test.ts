import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Behind an auth proxy (SSO) the manifest request must carry the session cookie, otherwise the
// proxy answers with a sign-in page and the browser refuses to install the app. A <link rel="manifest">
// is fetched without credentials unless it says crossorigin="use-credentials".
// A text check on index.html: whether the browser really sends the cookie is not observable here.
describe("index.html manifest link", () => {
  it("is the one manifest of the app and is fetched with credentials", () => {
    const html = readFileSync(resolve(__dirname, "..", "index.html"), "utf8");
    const doc = new DOMParser().parseFromString(html, "text/html");
    const links = doc.querySelectorAll('link[rel="manifest"]');
    expect(links).toHaveLength(1);
    expect(links[0]!.getAttribute("href")).toBe("/manifest.webmanifest");
    expect(links[0]!.getAttribute("crossorigin")).toBe("use-credentials");
  });
});
