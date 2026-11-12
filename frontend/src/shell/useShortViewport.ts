import { useEffect, useState } from "react";

/** Same limit as the `short` variant in index.css. */
export const SHORT_VIEWPORT_PX = 560;

/** Browsers report 1 with small rounding differences for a page that is not zoomed. */
const MAX_UNZOOMED_SCALE = 1.01;

function isShort(): boolean {
  const viewport = window.visualViewport;
  // A pinch-zoomed page also has a small visual viewport, but no keyboard: leave the layout alone.
  return viewport != null && viewport.scale <= MAX_UNZOOMED_SCALE && viewport.height < SHORT_VIEWPORT_PX;
}

/**
 * True while little of the page is visible, in practice: the on-screen keyboard is open.
 *
 * Where the layout viewport shrinks with the keyboard (`interactive-widget=resizes-content`), the
 * `short` media query sees it on its own. iOS Safari keeps the layout viewport and only shrinks
 * the visual one, so the media query never matches there; this hook reads the visual viewport
 * and the screen sets `data-short`, which the same `short` variant answers to.
 */
export function useShortViewport(): boolean {
  const [short, setShort] = useState(isShort);

  useEffect(() => {
    const viewport = window.visualViewport;
    if (viewport == null) return;
    const update = () => setShort(isShort());
    update();
    viewport.addEventListener("resize", update);
    return () => viewport.removeEventListener("resize", update);
  }, []);

  return short;
}
