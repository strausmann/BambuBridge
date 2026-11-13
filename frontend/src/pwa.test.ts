import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { pwaOptions, precacheGlobs } from "../pwa.config";
import { isPublicPath, PUBLIC_PATHS } from "./app/publicPaths";

const workbox = pwaOptions.workbox!;
const dist = resolve(__dirname, "..", "dist");
const required = process.env.REQUIRE_DIST === "1";

describe("public path list", () => {
  it("is the list an auth proxy lets through without a sign-in", () => {
    expect(PUBLIC_PATHS).toEqual(["/sw.js", "/manifest.webmanifest", "/index.html", "/theme-init.js", "/favicon.svg", "/favicon.ico", "/icons/*", "/assets/*"]);
  });

  it("a directory entry covers one file directly in it, nothing above or below", () => {
    expect(isPublicPath("/assets/index-abc.js")).toBe(true);
    expect(isPublicPath("/icons/icon-192.png")).toBe(true);
    for (const path of ["/assets/", "/assets", "/assets/x/y.js", "/assetsx/a.js", "/icons/../api/v1/x", "/api/v1/auth/session", "/sw.js.map", "/", "/licenses/inter-OFL-1.1.txt"]) {
      expect(isPublicPath(path), path).toBe(false);
    }
  });
});

describe("service worker", () => {
  it("never answers the API, the sign-in hop, the docs or the OpenAPI document", () => {
    expect(workbox.navigateFallback).toBe("/index.html");
    const deny = workbox.navigateFallbackDenylist ?? [];
    for (const path of ["/api/v1/events", "/api/v1/auth/session", "/auth/continue", "/auth/continue?next=%2Fprotocol", "/docs", "/docs/oauth2-redirect", "/openapi.json"]) {
      expect(
        deny.some((re) => re.test(path)),
        path,
      ).toBe(true);
    }
    for (const path of ["/", "/providers", "/protocol", "/settings", "/settings/auth", "/device", "/sign-in", "/apiary", "/authors", "/docsy"]) {
      expect(
        deny.some((re) => re.test(path)),
        path,
      ).toBe(false);
    }
    // No runtime route at all: the worker serves the precached shell files and nothing else.
    expect(workbox.runtimeCaching).toEqual([]);
    expect(pwaOptions.registerType).toBe("prompt");
    expect(workbox.skipWaiting).toBe(false);
    expect(workbox.inlineWorkboxRuntime).toBe(true);
    expect(pwaOptions.manifest).toBe(false);
  });

  it("precaches only public paths, never the worker itself", () => {
    expect(precacheGlobs).toEqual(["manifest.webmanifest", "index.html", "theme-init.js", "favicon.svg", "favicon.ico", "icons/*", "assets/*"]);
    expect(workbox.globPatterns).toEqual(precacheGlobs);
  });
});

/** The precache manifest workbox wrote into sw.js: `[{url:"...",revision:...},...]`. */
function precachedUrls(sw: string): string[] {
  return [...sw.matchAll(/\burl:"([^"]+)"/g)].map((m) => `/${m[1]!.replace(/^\//, "")}`);
}

describe.runIf(required)("built service worker", () => {
  it("every precached URL and every file at the root of dist/ is on the public path list", () => {
    const sw = readFileSync(join(dist, "sw.js"), "utf8");
    const urls = precachedUrls(sw);
    expect(urls).toContain("/index.html");
    expect(urls.some((url) => url.startsWith("/assets/") && url.endsWith(".js"))).toBe(true);
    expect(urls.filter((url) => !isPublicPath(url)), "precached but not public").toEqual([]);
    const rootFiles = readdirSync(dist)
      .filter((name) => statSync(join(dist, name)).isFile())
      .map((name) => `/${name}`);
    expect(rootFiles).toContain("/sw.js");
    expect(rootFiles.filter((path) => !isPublicPath(path)), "file at the root of dist/ that is not on the public path list").toEqual([]);
    // One worker file: the workbox runtime is inlined.
    expect(rootFiles.filter((path) => /workbox|registerSW/.test(path))).toEqual([]);
  });
});
