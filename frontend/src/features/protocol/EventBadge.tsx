import { useLingui } from "@lingui/react/macro";
import type { DeliveryStatus } from "../common/api";
import { Badge } from "../common/ui";

const tone = (status: DeliveryStatus) => (status === "done" ? "ok" : status === "pending" ? "info" : "bad");

export function useDeliveryLabel(): (status: DeliveryStatus) => string {
  const { t } = useLingui();
  return (status) => (status === "done" ? t`Zugestellt` : status === "pending" ? t`Ausstehend` : t`Fehlgeschlagen`);
}

export function DeliveryBadge({ status }: { status: DeliveryStatus }) {
  const label = useDeliveryLabel();
  return <Badge tone={tone(status)}>{label(status)}</Badge>;
}
