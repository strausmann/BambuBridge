import { useEffect, useState } from "react";

/** Same limit as the `short` variant in index.css. */
export const SHORT_VIEWPORT_PX = 560;

function isShort(): boolean {
  const viewport = window.visualViewport;
  return viewport != null && viewport.height < SHORT_VIEWPORT_PX;
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
