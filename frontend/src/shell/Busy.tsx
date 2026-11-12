import { useEffect, useState } from "react";

/** How long a request may take before the button says it is still working. */
export const BUSY_DELAY_MS = 300;

/** Follows `busy`, but only after `delay`: a quick answer never flashes a busy mark. */
export function useDelayedBusy(busy: boolean, delay = BUSY_DELAY_MS): boolean {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (!busy) return;
    const timer = window.setTimeout(() => setShown(true), delay);
    return () => {
      window.clearTimeout(timer);
      setShown(false);
    };
  }, [busy, delay]);

  return shown;
}

/**
 * Goes next to a button's label, which stays as it is. A turning ring, or an ellipsis for people
 * who asked for reduced motion. Decorative: the button is disabled while busy and the result is
 * announced by the screen that follows or by an error line.
 */
export function BusyMark({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span data-testid="busy-mark" aria-hidden="true" className="inline-flex">
      <svg viewBox="0 0 16 16" width="16" height="16" className="busy-ring motion-reduce:hidden">
        <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeOpacity="0.35" strokeWidth="2" />
        <path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <span className="hidden motion-reduce:inline">…</span>
    </span>
  );
}
