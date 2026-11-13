import { themes } from "../design/tokens";

export type ThemeChoice = "system" | "light" | "dark";

export const THEME_KEY = "bb.theme";
export const THEME_CHOICES: readonly ThemeChoice[] = ["system", "light", "dark"];

export function isTheme(value: unknown): value is ThemeChoice {
  return value === "system" || value === "light" || value === "dark";
}

export function readTheme(): ThemeChoice {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return isTheme(value) ? value : "system";
  } catch {
    return "system"; // private window, blocked site data
  }
}

export function storeTheme(choice: ThemeChoice): void {
  try {
    localStorage.setItem(THEME_KEY, choice);
  } catch {
    /* the choice then lasts for this page load only */
  }
}

/**
 * The browser paints its own bars (status bar, address bar) in the `theme-color`. index.html has
 * one per colour scheme of the device; a chosen theme overrides both, `system` puts them back.
 */
function applyThemeColor(choice: ThemeChoice): void {
  for (const meta of document.head.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) {
    const scheme = meta.media.includes("dark") ? "dark" : "light";
    meta.content = themes[choice === "system" ? scheme : choice].bg;
  }
}

/** `system` removes the attribute so `prefers-color-scheme` decides (tokens.css). */
export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  applyThemeColor(choice);
}

type TransitionDocument = Document & { startViewTransition?: (update: () => void) => unknown };

/**
 * Apply a theme the user just picked. The whole page changes colour at once, so where the browser
 * can, the old and the new picture cross-fade (200 ms, index.css) instead of flipping; with reduced
 * motion, or without view transitions, the change is immediate.
 */
export function switchTheme(choice: ThemeChoice): void {
  const doc = document as TransitionDocument;
  const reduced = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced || typeof doc.startViewTransition !== "function") {
    applyTheme(choice);
    return;
  }
  doc.startViewTransition(() => applyTheme(choice));
}
