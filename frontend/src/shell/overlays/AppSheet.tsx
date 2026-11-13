import { Dialog, Modal, ModalOverlay } from "react-aria-components";
import type { OverlayProps } from "./AppDialog";
import { OverlayBody, OverlayHeader } from "./OverlayHeader";
import { useBackClosesOverlay } from "./useBackClosesOverlay";
import { useOpenUntilRevealed } from "./useOpenUntilRevealed";
import { useVisualViewport } from "./useVisualViewport";

/**
 * A sheet from the bottom edge on a phone, a centred panel from 640 px. Like the dialog it fits
 * the visible part of the page and scrolls inside; on a short viewport (keyboard open) it sits
 * at the top instead of under the keyboard. Back closes it.
 */
export function AppSheet({ isOpen, onOpenChange, title, children, actions }: OverlayProps) {
  const { short } = useVisualViewport();
  const close = () => onOpenChange(false);
  useBackClosesOverlay(isOpen, close);
  const { open, onEnter, track } = useOpenUntilRevealed(isOpen);
  return (
    <ModalOverlay
      isOpen={open}
      onEnter={onEnter}
      ref={track}
      onOpenChange={onOpenChange}
      isDismissable
      data-short={short || undefined}
      className="overlay-backdrop flex flex-col justify-end short:justify-start sm:items-center sm:justify-center sm:p-(--overlay-pad) sm:[--overlay-pad:--spacing(4)] sm:short:justify-start sm:short:[--overlay-pad:--spacing(2)]"
    >
      <Modal className="overlay-panel sheet-panel flex w-full flex-col overflow-hidden rounded-t-r3 border border-line bg-surface text-ink short:rounded-t-none short:rounded-b-r3 sm:max-w-lg sm:rounded-r3">
        <Dialog className="flex min-h-0 flex-1 flex-col outline-none">
          <OverlayHeader title={title} onClose={close} />
          <OverlayBody actions={actions}>{children}</OverlayBody>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
