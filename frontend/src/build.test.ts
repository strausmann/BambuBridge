import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const dist = resolve(__dirname, "..", "dist");
const backendCspFile = resolve(__dirname, "..", "..", "backend", "app", "web", "security_headers.py");
// CI runs this file after `pnpm build` with REQUIRE_DIST=1 (`pnpm build-test`) so a missing build
// fails instead of skipping.
const required = process.env.REQUIRE_DIST === "1";

function walk(dir: string, ...exts: string[]): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p, ...exts) : exts.some((ext) => p.endsWith(ext)) ? [p] : [];
  });
}

const rel = (file: string) => relative(dist, file);

/** Removes comments, so a URL in a licence banner or a source note is not counted. */
function withoutComments(file: string, text: string): string {
  if (file.endsWith(".html") || file.endsWith(".svg")) return text.replace(/<!--[\s\S]*?-->/g, "");
  return text.replace(/\/\*[\s\S]*?\*\//g, "");
}

/**
 * Absolute URLs that are names, not addresses anything is loaded from. Each entry has its reason;
 * a new URL in the bundle fails the test until it is judged here. `prefix` entries end in a `/`,
 * so they cannot be continued into another host; `exact` is the whole URL and nothing after it.
 */
const NOT_LOADED: { url: string; match: "prefix" | "exact"; why: string }[] = [
  { url: "http://www.w3.org/", match: "prefix", why: "XML namespaces (SVG, MathML, XLink, XHTML) that React and the SVG files name" },
  { url: "https://react.dev/errors/", match: "prefix", why: "link in React's production error messages" },
  { url: "http://localhost", match: "exact", why: "base for parsing relative URLs in TanStack Router, never requested" },
];

/** The entry that covers `url`, if any. */
function notLoaded(url: string): (typeof NOT_LOADED)[number] | undefined {
  return NOT_LOADED.find((entry) => (entry.match === "exact" ? url === entry.url : url.startsWith(entry.url)));
}

/**
 * Hashes in the backend's CSP list that this bundle does not produce, each with its reason. Every
 * other hash of the list must be produced by the bundle; an entry here that the bundle does
 * produce is stale and fails the test.
 */
const NOT_IN_THIS_BUNDLE: { hash: string; why: string }[] = [
  {
    hash: "gYiS/BvZvRcK27JIXTuwhZ3hs2+VJ1X+2gUlE+farlg=",
    why: "react-aria's iOS scroll lock (overscroll-behavior), injected while a modal is open; the shell has no modal yet, so the code is not in the bundle",
  },
];

describe("the URL allow-list", () => {
  it("has no prefix that could be continued into another host", () => {
    for (const entry of NOT_LOADED) if (entry.match === "prefix") expect(entry.url, entry.url).toMatch(/^https?:\/\/[^/]+\//);
  });

  it("takes http://localhost only as the whole URL", () => {
    expect(notLoaded("http://localhost")?.url).toBe("http://localhost");
    for (const url of ["http://localhost.evil.example/x.js", "http://localhost:8080/api", "http://localhost/x", "http://localhostile.example"]) {
      expect(notLoaded(url), url).toBeUndefined();
    }
    expect(notLoaded("http://www.w3.org/2000/svg")).toBeDefined();
    expect(notLoaded("http://www.w3.org.evil.example/")).toBeUndefined();
  });
});

describe.skipIf(!required && !existsSync(dist))("built output", () => {
  it("exists", () => {
    expect(existsSync(join(dist, "index.html")), "run `pnpm build` first").toBe(true);
  });

  it("loads no font or stylesheet from another host", () => {
    const files = walk(dist, ".css");
    expect(files.length).toBeGreaterThan(0);
    const offenders: string[] = [];
    for (const file of files) {
      const css = readFileSync(file, "utf8");
      for (const m of css.matchAll(/url\(\s*['"]?(https?:)?\/\/[^)]*\)/gi)) offenders.push(`${rel(file)}: ${m[0]}`);
      for (const m of css.matchAll(/@import\s+(url\()?\s*['"]?(https?:)?\/\//gi)) offenders.push(`${rel(file)}: ${m[0]}`);
    }
    expect(offenders).toEqual([]);
  });

  it("names no font host or CDN anywhere in the build", () => {
    const offenders: string[] = [];
    for (const file of walk(dist, ".js", ".css", ".html", ".svg", ".webmanifest", ".json")) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(/fonts\.googleapis|fonts\.gstatic|use\.typekit|cdn\.jsdelivr|unpkg\.com|cdnjs\.cloudflare|fonts\.bunny/gi)) offenders.push(`${rel(file)}: ${m[0]}`);
    }
    expect(offenders).toEqual([]);
  });

  it("holds no absolute http(s) URL outside comments, except names nothing is loaded from", () => {
    const offenders: string[] = [];
    const used = new Set<string>();
    for (const file of walk(dist, ".js", ".css", ".html", ".svg")) {
      const text = withoutComments(file, readFileSync(file, "utf8"));
      for (const m of text.matchAll(/https?:\/\/[^\s"'`<>)\\]*/gi)) {
        const known = notLoaded(m[0]);
        if (known) used.add(known.url);
        else offenders.push(`${rel(file)}: ${m[0]}`);
      }
    }
    expect(offenders).toEqual([]);
    // An entry nothing matches any more is stale: remove it, so the list never grows on its own.
    expect(NOT_LOADED.map(({ url }) => url).filter((url) => !used.has(url))).toEqual([]);
  });

  it("index.html has no inline script and no inline style; theme-init.js is a file of this origin", () => {
    const html = readFileSync(join(dist, "index.html"), "utf8");
    const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
    expect(scripts.length).toBeGreaterThanOrEqual(2);
    for (const [, attributes, body] of scripts) {
      expect(body!.trim(), "inline script in index.html").toBe("");
      expect(attributes).toMatch(/\bsrc="\/[^/"][^"]*"/);
    }
    expect(scripts.some(([, attributes]) => /src="\/theme-init\.js"/.test(attributes!))).toBe(true);
    expect(existsSync(join(dist, "theme-init.js"))).toBe(true);
    expect(html).not.toMatch(/<style\b/i);
    expect(html).not.toMatch(/\sstyle=/i);
    expect(html).not.toMatch(/\son[a-z]+=/i);
    // Every stylesheet, icon and script is a path on this origin.
    for (const m of html.matchAll(/\b(?:href|src)="([^"]*)"/gi)) expect(m[1], m[0]).toMatch(/^\/[^/]/);
  });

  it("sets the viewport for phones: safe areas and a layout that shrinks with the on-screen keyboard", () => {
    const html = readFileSync(join(dist, "index.html"), "utf8");
    expect(html).toContain('<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content" />');
    expect(html).not.toMatch(/user-scalable|maximum-scale/);
  });

  it("ships the self-hosted font files, latin subsets only", () => {
    const fonts = walk(dist, ".woff2").map(rel);
    for (const family of ["inter-latin-wght-normal", "inter-latin-ext-wght-normal", "space-grotesk-latin-wght-normal", "space-grotesk-latin-ext-wght-normal", "jetbrains-mono-latin-wght-normal"]) {
      expect(fonts.some((file) => file.includes(family)), family).toBe(true);
    }
    expect(fonts.filter((file) => /cyrillic|greek|vietnamese/.test(file))).toEqual([]);
    expect(walk(dist, ".woff", ".ttf", ".otf")).toEqual([]);
  });

  it("ships the licence notices the bundled fonts require", () => {
    for (const name of ["inter-OFL-1.1.txt", "space-grotesk-OFL-1.1.txt", "jetbrains-mono-OFL-1.1.txt"]) {
      expect(readFileSync(join(dist, "licenses", name), "utf8"), name).toContain("SIL OPEN FONT LICENSE Version 1.1");
    }
  });

  it("ships the icons generated from the brand mark and the logo files", () => {
    for (const file of ["favicon.ico", "favicon.svg", "icons/icon-192.png", "icons/icon-512.png", "icons/icon-maskable-512.png", "icons/apple-touch-icon-180.png"]) {
      expect(existsSync(join(dist, file)), file).toBe(true);
    }
    expect(readFileSync(join(dist, "favicon.svg"), "utf8")).toBe(readFileSync(resolve(__dirname, "..", "..", "docs", "brand", "logos", "drehscheibe-light-mark.svg"), "utf8"));
    const logos = walk(join(dist, "assets"), ".svg").map(rel);
    for (const name of ["drehscheibe-light-lockup", "drehscheibe-dark-lockup", "drehscheibe-light-mark", "drehscheibe-dark-mark"]) {
      expect(logos.some((file) => file.includes(name)), name).toBe(true);
    }
  });

  it("csp: the backend's style hashes and the inline styles of the bundle are the same set, and nothing broader is allowed", () => {
    const source = readFileSync(backendCspFile, "utf8");
    // The policy itself (the `CSP = (...)` expression), not the prose around it.
    const policy = /^CSP = \(\n([\s\S]*?)^\)/m.exec(source);
    expect(policy, "CSP constant not found in the backend").not.toBeNull();
    expect(policy![1]).not.toContain("unsafe-inline");
    expect(policy![1]).toContain("\"style-src 'self' \" + \" \".join(REACT_ARIA_STYLE_HASHES)");
    const list = /^REACT_ARIA_STYLE_HASHES[^=]*= \(\n([\s\S]*?)^\)/m.exec(source);
    expect(list, "style hash list not found in the backend").not.toBeNull();
    const allowed = [...list![1]!.matchAll(/"'sha256-([A-Za-z0-9+/=]+)'"/g)].map((m) => m[1]!);
    expect(allowed.length, "no style hash found in the backend CSP list").toBeGreaterThan(0);

    // react-aria injects its styles at runtime (a touch-action rule, an iOS scroll lock). They live
    // in whichever chunk holds the component, so every script of the build is searched, not one.
    const scripts = walk(join(dist, "assets"), ".js").map((file) => ({ file, code: readFileSync(file, "utf8") }));
    const holders = scripts.filter(({ code }) => code.includes("react-aria-pressable-style"));
    expect(holders.length, "react-aria no longer injects its pressable style; drop its hash from the backend CSP").toBeGreaterThan(0);

    const found: { file: string; text: string }[] = [];
    const unaccounted: string[] = [];
    for (const { file, code } of scripts) {
      for (const m of code.matchAll(/createElement\(`style`\)/g)) {
        const window = code.slice(m.index, m.index + 400);
        // `x.textContent=`...`` (maybe followed by .trim()): a template in the minified bundle.
        const quoted = /textContent=`([^`]*)`(\.trim\(\))?/.exec(window);
        if (quoted) {
          // `${name}` is a constant of the bundle (the attribute the rule targets): look its text up.
          const filled = quoted[1]!.replace(/\$\{(\w+)\}/g, (_all, name: string) => {
            const value = new RegExp(`\\b${name}=\`([^\`]*)\``).exec(code);
            expect(value, `constant ${name} used in an inline style could not be resolved`).not.toBeNull();
            return value![1]!;
          });
          found.push({ file, text: quoted[2] ? filled.trim() : filled });
        } else if (!/data-precedence/.test(code.slice(Math.max(0, m.index - 300), m.index + 100))) {
          // React DOM's own `<style precedence>` hoisting; the app renders none. Anything else is unknown.
          unaccounted.push(`${rel(file)}@${m.index}`);
        }
      }
    }
    expect(unaccounted, "a style element is created without a visible text: add a hash or remove it").toEqual([]);
    expect(found.length, "react-aria's inline styles were expected").toBeGreaterThanOrEqual(1);
    const produced = found.map(({ file, text }) => ({ file, text, hash: createHash("sha256").update(text).digest("base64") }));
    const missing = produced
      .filter(({ hash }) => !allowed.includes(hash))
      .map(({ file, text, hash }) => `${rel(file)}: sha256-${hash} for ${JSON.stringify(text)}`);
    expect(missing, "inline style without a CSP hash in backend/app/web/security_headers.py").toEqual([]);

    // The other direction: a hash the bundle does not produce allows a style nobody ships.
    const producedHashes = new Set(produced.map(({ hash }) => hash));
    const excused = NOT_IN_THIS_BUNDLE.map(({ hash }) => hash);
    const unused = allowed.filter((hash) => !producedHashes.has(hash) && !excused.includes(hash));
    expect(unused, "hash in the backend CSP list that no inline style of the bundle has: remove it there").toEqual([]);
    expect(excused.filter((hash) => producedHashes.has(hash)), "the bundle now produces this style: remove it from NOT_IN_THIS_BUNDLE").toEqual([]);
    expect(excused.filter((hash) => !allowed.includes(hash)), "not in the backend CSP list any more: remove it from NOT_IN_THIS_BUNDLE").toEqual([]);
  });

  it("csp: the bundle sets no style attribute through markup strings", () => {
    // `style-src 'self'` blocks style="" attributes in parsed markup; styles set through the CSSOM pass.
    const offenders = walk(join(dist, "assets"), ".js").filter((file) => /innerHTML\s*=\s*`[^`]*style=/.test(readFileSync(file, "utf8")));
    expect(offenders.map(rel)).toEqual([]);
  });
});
