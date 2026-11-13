import { useEffect, useRef } from "react";

let counter = 0;

/** The overlay entry a history state belongs to (`bbOverlay`), if any. */
function overlayOf(state: unknown): unknown {
  return typeof state === "object" && state !== null ? (state as { bbOverlay?: unknown }).bbOverlay : undefined;
}

/**
 * Before an overlay action navigates: the current entry, if an overlay added it, becomes the
 * page's own entry again (`replaceState` without the overlay mark). The navigation then pushes
 * after the page, and Back from the new page lands on the page, not on an entry of an overlay
 * that is no longer open. The overlay sees its entry gone and leaves the history alone.
 */
export function leaveOverlayHistory(): void {
  const state: unknown = window.history.state;
  if (overlayOf(state) === undefined) return;
  const page = { ...(state as Record<string, unknown>) };
  delete page.bbOverlay;
  window.history.replaceState(page, "");
}

/**
 * Back closes an open overlay, as on a phone it is expected to, instead of leaving the page.
 *
 * Opening pushes a history entry for the same address (the router's own state is kept, so it
 * sees no change of page). Back pops it: `popstate` closes the overlay and the page stays.
 * Closed any other way, the overlay takes its entry back out, so Back afterwards goes where it
 * went before. A navigation away while it was open leaves the history alone; an action that
 * navigates calls `leaveOverlayHistory()` first.
 *
 * Taking the entry out waits a moment: React's StrictMode runs the effect, its cleanup and the
 * effect again at once, and the second run keeps the entry instead of pushing a new one while
 * the `back()` of the first is still on its way (which would land on the first entry and close
 * the overlay).
 */
export function useBackClosesOverlay(isOpen: boolean, close: () => void): void {
  const closeRef = useRef(close);
  useEffect(() => {
    closeRef.current = close;
  }, [close]);
  const entry = useRef<{ id: number; pendingBack?: number } | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let id: number;
    if (entry.current !== null && overlayOf(window.history.state) === entry.current.id) {
      // The effect ran again for the same open overlay: keep its entry.
      window.clearTimeout(entry.current.pendingBack);
      id = entry.current.id;
    } else {
      counter += 1;
      id = counter;
      const previous: unknown = window.history.state;
      window.history.pushState({ ...(typeof previous === "object" && previous !== null ? previous : {}), bbOverlay: id }, "");
    }
    const own: { id: number; pendingBack?: number } = { id };
    entry.current = own;
    let poppedByBack = false;
    const onPop = () => {
      if (overlayOf(window.history.state) === id) return;
      poppedByBack = true;
      closeRef.current();
    };
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      if (poppedByBack || overlayOf(window.history.state) !== id) {
        entry.current = null;
        return;
      }
      own.pendingBack = window.setTimeout(() => {
        if (entry.current === own) entry.current = null;
        if (overlayOf(window.history.state) === id) window.history.back();
      }, 0);
    };
  }, [isOpen]);
}
