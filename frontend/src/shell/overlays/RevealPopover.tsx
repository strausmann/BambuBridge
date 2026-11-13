import { useContext, useEffect, useState, type ReactNode } from "react";
import { OverlayTriggerStateContext, Popover, type PopoverProps } from "react-aria-components";

/**
 * Tells `RevealPopover` when its content was revealed (`isEntering` is true from the render in which
 * React Aria reveals it), and forgets that again when the content is gone.
 */
function RevealProbe({ isEntering, setRevealed }: { isEntering: boolean; setRevealed: (revealed: boolean) => void }) {
  useEffect(() => {
    if (isEntering) setRevealed(true);
  }, [isEntering, setRevealed]);
  useEffect(() => () => setRevealed(false), [setRevealed]);
  return null;
}

/**
 * A `Popover` that is removed at once when it is closed before it was revealed.
 *
 * On a touch device a popover that just opened stays hidden for two animation frames (longer after
 * a text field took the focus: the on-screen keyboard is on its way) before React Aria reveals it,
 * and the reveal cancels every CSS transition running on it. A popover closed within that window
 * has started its exit transitions by then; the reveal cancels exactly those, the exit never hears
 * that they ended and the popover stays half-way out (`data-exiting`) over the page for good - the
 * same defect as with `ModalOverlay` (`useOpenUntilRevealed`). Unlike a modal overlay a popover
 * has nothing to wait for: it was never visible, so there is nothing to animate out. It is
 * therefore unmounted at once (React Aria's `shouldSkipAnimation`) as long as it has not been
 * revealed; once it was, it leaves with its animation as usual.
 *
 * Must be rendered inside the component that owns the popover's open state (`ComboBox`): it reads
 * that state from `OverlayTriggerStateContext`, so the skip is in force in the very render in which
 * the popover closes.
 */
export function RevealPopover({ children, ...props }: Omit<PopoverProps, "children" | "shouldSkipAnimation"> & { children: ReactNode }) {
  const isOpen = useContext(OverlayTriggerStateContext)?.isOpen ?? false;
  const [revealed, setRevealed] = useState(false);
  return (
    <Popover {...props} shouldSkipAnimation={!revealed && !isOpen}>
      {({ isEntering }) => (
        <>
          <RevealProbe isEntering={isEntering} setRevealed={setRevealed} />
          {children}
        </>
      )}
    </Popover>
  );
}
