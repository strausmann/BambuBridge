import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { contrastRatio, EDGE_PAIRS, radii, TEXT_PAIRS, themes, type Role } from "./tokens";

const css = readFileSync(resolve(__dirname, "tokens.css"), "utf8");
const brand = readFileSync(resolve(__dirname, "..", "..", "..", "docs", "brand", "tokens.css"), "utf8");

/** Collect `--name: value;` declarations of the first block that starts with `selector`. */
function block(source: string, selector: string): Record<string, string> {
  const start = source.indexOf(selector);
  if (start < 0) throw new Error(`selector not found: ${selector}`);
  const open = source.indexOf("{", start);
  const end = source.indexOf("}", open);
  const out: Record<string, string> = {};
  for (const m of source.slice(open + 1, end).matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) out[m[1]!] = m[2]!.trim();
  return out;
}

const roles = Object.keys(themes.light) as Role[];

describe("contrast", () => {
  it("computes the WCAG ratio for black on white", () => {
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 5);
    expect(contrastRatio("#FFFFFF", "#FFFFFF")).toBeCloseTo(1, 5);
  });

  for (const theme of ["light", "dark"] as const) {
    it(`every text/surface pair reaches 4.5:1 in the ${theme} theme`, () => {
      const t = themes[theme];
      const failures = TEXT_PAIRS.map(([fg, bg]) => ({ fg, bg, ratio: contrastRatio(t[fg], t[bg]) }))
        .filter(({ ratio }) => ratio < 4.5)
        .map(({ fg, bg, ratio }) => `${theme}: ${fg} ${t[fg]} on ${bg} ${t[bg]} = ${ratio.toFixed(2)}`);
      expect(failures).toEqual([]);
    });

    it(`input edges reach 3:1 in the ${theme} theme`, () => {
      const t = themes[theme];
      for (const [edge, surface] of EDGE_PAIRS) {
        expect(contrastRatio(t[edge], t[surface]), `${theme}: ${edge} on ${surface}`).toBeGreaterThanOrEqual(3);
      }
    });
  }

  it("covers every text role on every plain surface", () => {
    // A text role missing from the table would be unchecked: the table must name each one on bg and surface.
    for (const text of ["ink", "ink-2", "ink-3", "link", "primary", "accent", "ok", "warn", "bad", "info"] as const) {
      for (const surface of ["bg", "surface"] as const) {
        expect(TEXT_PAIRS.some(([a, b]) => a === text && b === surface), `${text} on ${surface}`).toBe(true);
      }
    }
  });
});

describe("tokens.css", () => {
  it("starts with a verbatim copy of docs/brand/tokens.css", () => {
    expect(css.startsWith(brand)).toBe(true);
  });

  it("light values equal tokens.ts", () => {
    const light = block(css, "\n:root {");
    for (const role of roles) expect(light[`--${role}`]?.toUpperCase(), `light --${role}`).toBe(themes.light[role].toUpperCase());
  });

  it("dark values match under [data-theme=dark] and under the media query", () => {
    const explicit = block(css, ':root[data-theme="dark"]');
    const mediaStart = css.indexOf("@media (prefers-color-scheme: dark)");
    expect(mediaStart).toBeGreaterThan(-1);
    const media = block(css.slice(mediaStart), ':root:not([data-theme="light"])');
    for (const role of roles) {
      expect(explicit[`--${role}`]?.toUpperCase(), `explicit --${role}`).toBe(themes.dark[role].toUpperCase());
      expect(media[`--${role}`]?.toUpperCase(), `media --${role}`).toBe(themes.dark[role].toUpperCase());
    }
  });

  it("radii equal tokens.ts", () => {
    const theme = block(css, "@theme {");
    for (const [name, value] of Object.entries(radii)) expect(theme[`--radius-${name}`], name).toBe(value);
  });

  it("names the self-hosted font families behind the font tokens", () => {
    const theme = block(css, "@theme {");
    expect(theme["--font-sans"]).toContain('"Inter Variable"');
    expect(theme["--font-display"]).toContain('"Space Grotesk Variable"');
    expect(theme["--font-mono"]).toContain('"JetBrains Mono Variable"');
  });

  it("defines no external urls", () => {
    expect(css).not.toMatch(/https?:\/\//);
  });
});
