import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test-utils";
import { contrastRatio, themes, THUMB_RING } from "../design/tokens";
import { ThemeSwitch } from "./ThemeSwitch";
import { applyTheme, readTheme, storeTheme, switchTheme, THEME_KEY } from "./theme";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("theme", () => {
  it("defaults to the system theme and ignores an unknown stored value", () => {
    expect(readTheme()).toBe("system");
    localStorage.setItem(THEME_KEY, "sepia");
    expect(readTheme()).toBe("system");
  });

  it("stores the choice and sets or removes data-theme", () => {
    storeTheme("dark");
    expect(readTheme()).toBe("dark");
    applyTheme("dark");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    applyTheme("system");
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("survives blocked site data", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readTheme()).toBe("system");
    expect(() => storeTheme("light")).not.toThrow();
  });

  it("cross-fades through a view transition where the browser has one", () => {
    const start = vi.fn((update: () => void) => update());
    Object.defineProperty(document, "startViewTransition", { value: start, configurable: true });
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query }));
    switchTheme("dark");
    expect(start).toHaveBeenCalledTimes(1);
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    Reflect.deleteProperty(document, "startViewTransition");
  });

  it("changes at once with reduced motion", () => {
    const start = vi.fn();
    Object.defineProperty(document, "startViewTransition", { value: start, configurable: true });
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), media: query }));
    switchTheme("light");
    expect(start).not.toHaveBeenCalled();
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    Reflect.deleteProperty(document, "startViewTransition");
  });

  it("theme-init.js applies the stored choice under the same key", () => {
    const source = readFileSync(resolve(__dirname, "..", "..", "public", "theme-init.js"), "utf8");
    expect(source).toContain(`localStorage.getItem("${THEME_KEY}")`);
    localStorage.setItem(THEME_KEY, "dark");
    new Function(source)();
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    document.documentElement.removeAttribute("data-theme");
    localStorage.setItem(THEME_KEY, "system");
    new Function(source)();
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });
});

describe("theme-color", () => {
  function metas(): HTMLMetaElement[] {
    return [...document.head.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')];
  }

  afterEach(() => metas().forEach((meta) => meta.remove()));

  it("index.html starts with the page background of each scheme", () => {
    const html = readFileSync(resolve(__dirname, "..", "..", "index.html"), "utf8");
    expect(html).toContain(`<meta name="theme-color" media="(prefers-color-scheme: light)" content="${themes.light.bg}" />`);
    expect(html).toContain(`<meta name="theme-color" media="(prefers-color-scheme: dark)" content="${themes.dark.bg}" />`);
  });

  it("follows a chosen theme in both schemes and goes back to the device's with system", () => {
    for (const scheme of ["light", "dark"]) {
      const meta = document.createElement("meta");
      meta.name = "theme-color";
      meta.media = `(prefers-color-scheme: ${scheme})`;
      meta.content = scheme === "light" ? themes.light.bg : themes.dark.bg;
      document.head.append(meta);
    }
    applyTheme("dark");
    expect(metas().map((meta) => meta.content)).toEqual([themes.dark.bg, themes.dark.bg]);
    applyTheme("light");
    expect(metas().map((meta) => meta.content)).toEqual([themes.light.bg, themes.light.bg]);
    applyTheme("system");
    expect(metas().map((meta) => meta.content)).toEqual([themes.light.bg, themes.dark.bg]);
  });

  it("does nothing without the meta elements", () => {
    expect(() => applyTheme("dark")).not.toThrow();
  });
});

describe("ThemeSwitch", () => {
  it("marks the chosen option with a ring that is visible against the track and the thumb (3:1)", () => {
    const { container } = renderWithProviders(<ThemeSwitch />);
    const thumb = container.querySelector("span[aria-hidden]")!;
    expect(thumb.className).toContain(`border-${THUMB_RING.edge}`);
    expect(thumb.className).toContain(`bg-${THUMB_RING.thumb}`);
    expect(container.querySelector('[role="radiogroup"]')!.className).toContain(`bg-${THUMB_RING.track}`);
    for (const theme of ["light", "dark"] as const) {
      const t = themes[theme];
      expect(contrastRatio(t[THUMB_RING.edge], t[THUMB_RING.track]), `${theme}: ring on track`).toBeGreaterThanOrEqual(3);
      expect(contrastRatio(t[THUMB_RING.edge], t[THUMB_RING.thumb]), `${theme}: ring on thumb`).toBeGreaterThanOrEqual(3);
    }
  });

  it("offers system, light and dark, and applies and remembers the choice", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ThemeSwitch />);
    const group = screen.getByRole("radiogroup", { name: "Design" });
    expect(screen.getByRole("radio", { name: "Systemdesign" })).toBeChecked();
    expect(group).toHaveAttribute("data-choice", "system");

    await user.click(screen.getByRole("radio", { name: "Dunkles Design" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    // The sliding thumb reads its position from this attribute (no inline style under the CSP).
    expect(group).toHaveAttribute("data-choice", "dark");

    await user.click(screen.getByRole("radio", { name: "Systemdesign" }));
    expect(document.documentElement).not.toHaveAttribute("data-theme");
    expect(localStorage.getItem(THEME_KEY)).toBe("system");
  });

  it("starts from the stored choice", () => {
    localStorage.setItem(THEME_KEY, "light");
    renderWithProviders(<ThemeSwitch />);
    expect(screen.getByRole("radio", { name: "Helles Design" })).toBeChecked();
  });
});
