import type { ReactNode } from "react";
import { Dialog, Modal, ModalOverlay } from "react-aria-components";
import { OverlayBody, OverlayHeader } from "./OverlayHeader";
import { useBackClosesOverlay } from "./useBackClosesOverlay";
import { useOpenUntilRevealed } from "./useOpenUntilRevealed";
import { useVisualViewport } from "./useVisualViewport";

export interface OverlayProps {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  title: string;
  children: ReactNode;
  /** Buttons at the end of the content; the main one last. */
  actions?: ReactNode;
}

/**
 * A centred dialog. It fits the visible part of the page (`--vvh`, the height above the
 * on-screen keyboard) and scrolls inside; on a short viewport it moves to the top, so the
 * focused field and the buttons stay where they can be seen. Back closes it.
 */
export function AppDialog({ isOpen, onOpenChange, title, children, actions }: OverlayProps) {
  const { short } = useVisualViewport();
  const close = () => onOpenChange(false);
  useBackClosesOverlay(isOpen, close);
  const { open, onEnter, track } = useOpenUntilRevealed(isOpen);
  return (
    <ModalOverlay isOpen={open} onEnter={onEnter} ref={track} onOpenChange={onOpenChange} isDismissable data-short={short || undefined} className="overlay-backdrop grid place-items-center p-(--overlay-pad) [--overlay-pad:--spacing(4)] short:place-items-start short:justify-items-center short:[--overlay-pad:--spacing(2)]">
      <Modal className="overlay-panel dialog-panel flex w-full max-w-lg flex-col overflow-hidden rounded-r3 border border-line bg-surface text-ink">
        <Dialog className="flex min-h-0 flex-1 flex-col outline-none">
          <OverlayHeader title={title} onClose={close} />
          <OverlayBody actions={actions}>{children}</OverlayBody>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
