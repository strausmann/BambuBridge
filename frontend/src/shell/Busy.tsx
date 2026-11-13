import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { Button, type ButtonProps } from "react-aria-components";

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
 * A button's label with room for the busy mark. The label stays as it is; the mark (a turning
 * ring, or an ellipsis for people who asked for reduced motion) hangs beside it, out of the
 * flow, so its appearing cannot move the text. It takes 18 px beside the label (2 px gap, 16 px
 * ring), less than the side padding of every button it is used in (20 px): it stays inside the
 * button even when a long label wraps and fills its line, and costs the label no width.
 * Decorative: the button carries `aria-busy`.
 */
function BusyLabel({ show, children }: { show: boolean; children: ReactNode }) {
  return (
    <span className="relative">
      {children}
      {show ? (
        <span data-testid="busy-mark" aria-hidden="true" className="absolute top-1/2 left-full ml-0.5 inline-flex -translate-y-1/2">
          <svg viewBox="0 0 16 16" width="16" height="16" className="busy-ring motion-reduce:hidden">
            <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeOpacity="0.35" strokeWidth="2" />
            <path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <span className="hidden motion-reduce:inline">…</span>
        </span>
      ) : null}
    </span>
  );
}

interface BusyButtonProps extends Omit<ButtonProps, "children"> {
  /** This button's request is running. */
  busy: boolean;
  children: ReactNode;
  ref?: RefObject<HTMLButtonElement | null>;
}

/**
 * A button that says when its request is running: `aria-busy` at once, the mark beside the label
 * once the request takes longer than a moment. The button library does not pass `aria-busy`
 * through, so it is set on the element.
 */
export function BusyButton({ busy, children, ref, ...props }: BusyButtonProps) {
  const own = useRef<HTMLButtonElement>(null);
  const slow = useDelayedBusy(busy);

  useEffect(() => {
    const button = own.current;
    if (!button) return;
    if (busy) button.setAttribute("aria-busy", "true");
    else button.removeAttribute("aria-busy");
  }, [busy]);

  return (
    <Button
      {...props}
      ref={(element) => {
        own.current = element;
        if (ref) ref.current = element;
      }}
    >
      <BusyLabel show={slow}>{children}</BusyLabel>
    </Button>
  );
}
