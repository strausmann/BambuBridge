import { useLingui } from "@lingui/react/macro";
import type { ProviderInstance } from "../common/api";
import { Badge } from "../common/ui";

type State = ProviderInstance["status"]["state"];

const TONE = { connected: "ok", starting: "info", stopped: "neutral", disconnected: "warn", needs_secret: "warn", error: "bad" } as const satisfies Record<State, "ok" | "info" | "neutral" | "warn" | "bad">;

export function useStatusLabel(): (state: State) => string {
  const { t } = useLingui();
  return (state) => {
    switch (state) {
      case "connected":
        return t`Verbunden`;
      case "starting":
        return t`Startet`;
      case "stopped":
        return t`Angehalten`;
      case "disconnected":
        return t`Getrennt`;
      case "needs_secret":
        return t`Geheimnis fehlt`;
      case "error":
        return t`Fehler`;
    }
  };
}

/** The state of a provider instance, as shape and word. */
export function ProviderStatusBadge({ instance }: { instance: Pick<ProviderInstance, "enabled" | "status"> }) {
  const { t } = useLingui();
  const label = useStatusLabel();
  // A switched-off instance is stopped by choice, which is not a fault.
  if (!instance.enabled) return <Badge tone="neutral">{t`Deaktiviert`}</Badge>;
  return <Badge tone={TONE[instance.status.state]}>{label(instance.status.state)}</Badge>;
}
