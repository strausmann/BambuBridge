import { useCallback, useState } from "react";

/** React Aria animates overlays only where the browser can report running animations. */
function animates(): boolean {
  return typeof Element !== "undefined" && "getAnimations" in Element.prototype;
}

/**
 * Keeps a modal overlay open until React Aria has revealed it, so that closing it right after it
 * opened cannot leave it on screen.
 *
 * On a touch device `ModalOverlay` (react-aria-components 1.22) reveals an overlay that just opened
 * only after two animation frames, or after the on-screen keyboard has moved, if a text field took
 * the focus. Closed within that window (Back, Escape, a button), the overlay starts its exit and
 * waits for the transitions that are running then; the late reveal cancels exactly those
 * transitions, the exit never hears that they ended, and the overlay stays half-way out
 * (`data-exiting`) for good, over the page. The exit is therefore held back until the reveal:
 * `onEnter` (passed to `ModalOverlay`) is called by React Aria at the reveal.
 *
 * The hold starts only when the overlay opens from nothing (`track`, the `ref` of `ModalOverlay`, tells whether
 * an overlay is still on screen, for example while it leaves): one that is reopened during its exit
 * was revealed already and would never call `onEnter` again.
 */
export function useOpenUntilRevealed(isOpen: boolean): { open: boolean; onEnter: () => void; track: (element: HTMLElement | null) => void } {
  const [overlay, setOverlay] = useState<HTMLElement | null>(null);
  const [waiting, setWaiting] = useState(() => isOpen && animates());
  const [wasOpen, setWasOpen] = useState(isOpen);
  if (isOpen !== wasOpen) {
    setWasOpen(isOpen);
    if (isOpen && overlay === null && animates()) setWaiting(true);
  }
  const onEnter = useCallback(() => setWaiting(false), []);
  return { open: isOpen || waiting, onEnter, track: setOverlay };
}
