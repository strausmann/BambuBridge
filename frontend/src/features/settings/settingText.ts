import { useLingui } from "@lingui/react/macro";

/** The label of a runtime setting, in the user's language; an unknown key shows as it is. */
export function useSettingLabel(): (key: string) => string {
  const { t } = useLingui();
  return (key) => {
    switch (key) {
      case "events.dedup_window_seconds":
        return t`Zeitfenster gegen doppelte Ereignisse (Sekunden)`;
      case "retention.events_days":
        return t`Ereignisse aufbewahren (Tage)`;
      case "retention.communication_days":
        return t`Kommunikationsprotokoll aufbewahren (Tage)`;
      case "sso.user_header":
        return t`Kopfzeile mit dem Benutzernamen`;
      case "sso.trust_header":
        return t`Kopfzeile mit dem Vertrauens-Token`;
      case "sso.trust_token":
        return t`Vertrauens-Token (leer schaltet SSO aus)`;
      case "auth.sign_in_limit_per_minute":
        return t`Anmeldeversuche pro Minute`;
      case "auth.identity_providers":
        return t`Anmeldedienste (in dieser Reihenfolge gefragt)`;
      default:
        return key;
    }
  };
}
