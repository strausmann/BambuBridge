import { useLingui } from "@lingui/react/macro";
import { Button, Heading } from "react-aria-components";
import { CloseIcon } from "../icons";
import { ICON_BUTTON } from "../ui";

/** Title and close button of a dialog or sheet; the title names the dialog for screen readers. */
export function OverlayHeader({ title, onClose }: { title: string; onClose: () => void }) {
  const { t } = useLingui();
  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-line py-2 pr-2 pl-5">
      <Heading slot="title" className="min-w-0 flex-1 text-section font-bold">
        {title}
      </Heading>
      <Button aria-label={t`Schließen`} onPress={onClose} className={ICON_BUTTON}>
        <CloseIcon />
      </Button>
    </div>
  );
}

/**
 * The scrolling part. The actions come last inside it, not pinned below: with the keyboard open
 * there is no room for a fixed footer, and the field being typed in must stay visible.
 */
export function OverlayBody({ children, actions }: { children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pt-4 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
      <div className="flex flex-col gap-4">{children}</div>
      {actions ? <div className="mt-6 flex flex-wrap justify-end gap-3">{actions}</div> : null}
    </div>
  );
}
