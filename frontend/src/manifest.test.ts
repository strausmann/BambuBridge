import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { isPublicPath } from "./app/publicPaths";

const root = resolve(__dirname, "..");
const dist = join(root, "dist");
const required = process.env.REQUIRE_DIST === "1";

interface Icon {
  src: string;
  sizes: string;
  type: string;
  purpose?: string;
}

const manifest = JSON.parse(readFileSync(join(root, "public", "manifest.webmanifest"), "utf8")) as Record<string, unknown>;
const icons = manifest.icons as Icon[];

describe("web app manifest", () => {
  it("installs as a standalone app on the whole origin", () => {
    expect(manifest).toMatchObject({ id: "/", start_url: "/", scope: "/", display: "standalone", name: "BambuBridge", short_name: "BambuBridge" });
  });

  it("has a 192 and a 512 icon and a maskable 512, all public files", () => {
    expect(icons.find((i) => i.sizes === "192x192" && i.purpose === undefined)?.src).toBe("/icons/icon-192.png");
    expect(icons.find((i) => i.sizes === "512x512" && i.purpose === undefined)?.src).toBe("/icons/icon-512.png");
    expect(icons.find((i) => i.purpose === "maskable")).toMatchObject({ sizes: "512x512", src: "/icons/icon-maskable-512.png" });
    for (const icon of icons) {
      expect(icon.type, icon.src).toBe("image/png");
      expect(isPublicPath(icon.src), icon.src).toBe(true);
    }
  });

  it("index.html carries the iOS home-screen tags", () => {
    const doc = new DOMParser().parseFromString(readFileSync(join(root, "index.html"), "utf8"), "text/html");
    expect(doc.querySelector('link[rel="apple-touch-icon"]')?.getAttribute("href")).toBe("/icons/apple-touch-icon-180.png");
    expect(doc.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]')?.getAttribute("content")).toBe("default");
    expect(doc.querySelector('meta[name="apple-mobile-web-app-title"]')?.getAttribute("content")).toBe("BambuBridge");
  });
});

describe.runIf(required)("manifest in the build", () => {
  it("is copied as it is and every icon it names exists", () => {
    expect(readFileSync(join(dist, "manifest.webmanifest"), "utf8")).toBe(readFileSync(join(root, "public", "manifest.webmanifest"), "utf8"));
    for (const icon of icons) expect(existsSync(join(dist, icon.src)), icon.src).toBe(true);
    expect(existsSync(join(dist, "icons", "apple-touch-icon-180.png"))).toBe(true);
  });
});
