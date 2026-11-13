import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const html = readFileSync(resolve(__dirname, "..", "index.html"), "utf8");
const doc = new DOMParser().parseFromString(html, "text/html");
const tokens = readFileSync(resolve(__dirname, "design", "tokens.css"), "utf8");

/** `--bg` of the light theme (the first block) and of the dark theme (the media query block). */
function backgrounds(): { light: string; dark: string } {
  const values = [...tokens.matchAll(/--bg:\s*(#[0-9A-Fa-f]{6})/g)].map((m) => m[1]!.toUpperCase());
  return { light: values[0]!, dark: values[1]! };
}

describe("index.html meta tags", () => {
  it("viewport: safe areas, a layout that shrinks with the on-screen keyboard, zoom left alone", () => {
    const metas = doc.querySelectorAll('meta[name="viewport"]');
    expect(metas).toHaveLength(1);
    expect(metas[0]!.getAttribute("content")).toBe("width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content");
  });

  it("theme-color per colour scheme, from the --bg token of each theme", () => {
    const { light, dark } = backgrounds();
    const color = (scheme: string) => doc.querySelector(`meta[name="theme-color"][media="(prefers-color-scheme: ${scheme})"]`)?.getAttribute("content")?.toUpperCase();
    expect(color("light")).toBe(light);
    expect(color("dark")).toBe(dark);
    expect(doc.querySelectorAll('meta[name="theme-color"]')).toHaveLength(2);
  });
});
