import { useEffect, useRef } from "react";

let counter = 0;

/** The overlay entry a history state belongs to (`bbOverlay`), if any. */
function overlayOf(state: unknown): unknown {
  return typeof state === "object" && state !== null ? (state as { bbOverlay?: unknown }).bbOverlay : undefined;
}

/**
 * Back closes an open overlay, as on a phone it is expected to, instead of leaving the page.
 *
 * Opening pushes a history entry for the same address (the router's own state is kept, so it
 * sees no change of page). Back pops it: `popstate` closes the overlay and the page stays.
 * Closed any other way, the overlay takes its entry back out, so Back afterwards goes where it
 * went before. A navigation away while it was open leaves the history alone.
 */
export function useBackClosesOverlay(isOpen: boolean, close: () => void): void {
  const closeRef = useRef(close);
  useEffect(() => {
    closeRef.current = close;
  }, [close]);

  useEffect(() => {
    if (!isOpen) return;
    counter += 1;
    const id = counter;
    const previous: unknown = window.history.state;
    window.history.pushState({ ...(typeof previous === "object" && previous !== null ? previous : {}), bbOverlay: id }, "");
    let poppedByBack = false;
    const onPop = () => {
      if (overlayOf(window.history.state) === id) return;
      poppedByBack = true;
      closeRef.current();
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      if (!poppedByBack && overlayOf(window.history.state) === id) window.history.back();
    };
  }, [isOpen]);
}
