import { useLingui } from "@lingui/react/macro";
import { useQuery } from "@tanstack/react-query";
import { Button } from "react-aria-components";
import { apiFetch } from "../../api/client";
import { AppSheet } from "../../shell/overlays/AppSheet";
import { SECONDARY_BUTTON } from "../../shell/ui";
import type { EventDetailData } from "../common/api";
import { formatDateTime, prettyJson } from "../common/format";
import { Code, DataBlock, LoadError, Loading } from "../common/ui";
import { DeliveryBadge } from "./EventBadge";

/** One event with its payload and what became of its delivery to each subscriber. */
export function EventDetail({ eventId, sourceName, onClose }: { eventId: string; sourceName: (id: string | null) => string; onClose: () => void }) {
  const { t } = useLingui();
  const detail = useQuery({ queryKey: ["events", "detail", eventId], queryFn: () => apiFetch<EventDetailData>(`/api/v1/events/${encodeURIComponent(eventId)}`) });
  return (
    <AppSheet
      isOpen
      onOpenChange={(open) => !open && onClose()}
      title={t`Ereignis`}
      actions={
        <Button onPress={onClose} className={SECONDARY_BUTTON}>
          {t`Schließen`}
        </Button>
      }
    >
      {detail.isPending ? (
        <Loading />
      ) : detail.isError ? (
        <LoadError error={detail.error} onRetry={() => void detail.refetch()} />
      ) : (
        <div className="flex flex-col gap-4" data-testid="event-detail">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
            <dt className="text-ink-2">{t`Typ`}</dt>
            <dd className="min-w-0">
              <Code>{detail.data.type}</Code>
            </dd>
            <dt className="text-ink-2">{t`Zeit`}</dt>
            <dd>{formatDateTime(detail.data.occurred_at)}</dd>
            <dt className="text-ink-2">{t`Quelle`}</dt>
            <dd className="min-w-0 break-words">{sourceName(detail.data.source_instance_id)}</dd>
            <dt className="text-ink-2">{t`Zustellung`}</dt>
            <dd>
              <DeliveryBadge status={detail.data.delivery_status} />
            </dd>
            <dt className="text-ink-2">{t`Schemaversion`}</dt>
            <dd>{detail.data.schema_version}</dd>
            {detail.data.correlation_id ? (
              <>
                <dt className="text-ink-2">{t`Zusammenhang`}</dt>
                <dd className="min-w-0">
                  <Code>{detail.data.correlation_id}</Code>
                </dd>
              </>
            ) : null}
          </dl>
          <div>
            <h3 className="mb-1 font-semibold">{t`Nutzdaten`}</h3>
            <DataBlock label={t`Nutzdaten des Ereignisses`}>{prettyJson(detail.data.payload)}</DataBlock>
          </div>
          <div>
            <h3 className="mb-1 font-semibold">{t`Zustellungen`}</h3>
            {detail.data.deliveries.length === 0 ? (
              <p className="text-ink-2">{t`Keine Zustellung nötig.`}</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {detail.data.deliveries.map((delivery) => (
                  <li key={delivery.subscriber} className="flex flex-col gap-1 rounded-r2 border border-line p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <Code>{delivery.subscriber}</Code>
                      <DeliveryBadge status={delivery.status} />
                    </div>
                    <p className="text-small text-ink-2">{t`Versuche: ${delivery.attempts}`}</p>
                    {delivery.last_error ? <p className="text-small break-words">{delivery.last_error}</p> : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </AppSheet>
  );
}
