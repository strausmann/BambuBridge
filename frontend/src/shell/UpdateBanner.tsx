import { useLingui } from "@lingui/react/macro";
import { Button } from "react-aria-components";
import { applyUpdate, useUpdateState } from "../app/updates";
import { RefreshIcon } from "./icons";
import { Notice } from "./Notice";
import { FOCUS } from "./ui";

/** A newer version that was not applied by itself (someone is typing, or a reload did not help). */
export function UpdateBanner() {
  const { t } = useLingui();
  const { banner } = useUpdateState();
  if (!banner) return null;
  return (
    <Notice
      tone="info"
      icon={<RefreshIcon />}
      action={
        <Button onPress={() => void applyUpdate()} className={`press inline-flex min-h-11 shrink-0 items-center rounded-r2 px-3 font-semibold text-ink underline underline-offset-2 hover:bg-surface ${FOCUS}`}>
          {t`Neu laden`}
        </Button>
      }
    >
      {t`Neue Version – jetzt neu laden`}
    </Notice>
  );
}
