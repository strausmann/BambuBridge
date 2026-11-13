import { useSyncExternalStore } from "react";

/** Below this visible height the page counts as short (the `short` variant in index.css says the same). */
export const SHORT_VIEWPORT_PX = 560;

/** Browsers report 1 with small rounding differences for a page that is not zoomed. */
const MAX_UNZOOMED_SCALE = 1.01;

export interface VisualViewportState {
  /** Visible height in CSS pixels; null where the browser has no visual viewport. */
  height: number | null;
  /** How far the visible part is scrolled down within the layout viewport (iOS, keyboard open). */
  offsetTop: number;
  /** Little of the page is visible, in practice: the on-screen keyboard is open. */
  short: boolean;
}

const NONE: VisualViewportState = { height: null, offsetTop: 0, short: false };
let current: VisualViewportState = NONE;
const listeners = new Set<() => void>();

function read(): VisualViewportState {
  const viewport = window.visualViewport;
  if (viewport == null) return NONE;
  // A pinch-zoomed page also shows less, but no keyboard is open: leave the layout alone.
  const short = viewport.scale <= MAX_UNZOOMED_SCALE && viewport.height < SHORT_VIEWPORT_PX;
  return { height: viewport.height, offsetTop: viewport.offsetTop, short };
}

/**
 * `--vvh` and `--vv-top` on the root element: the visible height and its offset. Overlays size
 * and place themselves with them (`max-height: var(--vvh, 100dvh)`), so a sheet ends above the
 * on-screen keyboard instead of under it.
 */
function publish(): void {
  const next = read();
  const style = document.documentElement.style;
  if (next.height === null) {
    style.removeProperty("--vvh");
    style.removeProperty("--vv-top");
  } else {
    style.setProperty("--vvh", `${next.height}px`);
    style.setProperty("--vv-top", `${next.offsetTop}px`);
  }
  if (next.height !== current.height || next.offsetTop !== current.offsetTop || next.short !== current.short) {
    current = next;
    listeners.forEach((listener) => listener());
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const viewport = window.visualViewport;
  if (listeners.size === 1) {
    publish();
    viewport?.addEventListener("resize", publish);
    viewport?.addEventListener("scroll", publish);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      viewport?.removeEventListener("resize", publish);
      viewport?.removeEventListener("scroll", publish);
    }
  };
}

/**
 * The visible part of the page. Where the layout viewport shrinks with the keyboard
 * (`interactive-widget=resizes-content`, Android), the media queries see it on their own; iOS
 * Safari keeps the layout viewport and shrinks only the visual one, so this hook reads that and
 * the CSS variables carry it to the overlays.
 */
export function useVisualViewport(): VisualViewportState {
  return useSyncExternalStore(subscribe, () => current, () => NONE);
}
