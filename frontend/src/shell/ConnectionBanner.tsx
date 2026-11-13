import { useLingui } from "@lingui/react/macro";
import { useOnline } from "../app/online";
import { OfflineIcon } from "./icons";
import { Notice } from "./Notice";

/** No network: the shell still opens (service worker), but nothing on screen is current. */
export function ConnectionBanner() {
  const { t } = useLingui();
  const online = useOnline();
  if (online) return null;
  return (
    <Notice tone="warn" icon={<OfflineIcon />}>
      <span className="font-semibold">{t`Keine Verbindung`}</span>
      <span className="block text-small text-ink-2">{t`Daten werden erst wieder angezeigt, wenn die Verbindung zurück ist.`}</span>
    </Notice>
  );
}
