import { useLingui } from "@lingui/react/macro";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { apiFetch } from "../../api/client";
import { TEXT_LINK } from "../../shell/ui";
import { LIVE_POLL_MS, useProviders, useReadiness, type EventPage, type ProviderInstance } from "../common/api";
import { formatDateTime } from "../common/format";
import { Badge, Card, Code, EmptyNote, LoadError, Loading, PageTitle } from "../common/ui";
import { DeliveryBadge } from "../protocol/EventBadge";
import { ProviderStatusBadge } from "../providers/ProviderStatusBadge";

const RECENT_EVENTS = 10;

export function OverviewPage() {
  const { t } = useLingui();
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <PageTitle>{t`Übersicht`}</PageTitle>
      <SystemCard />
      <InstancesCard />
      <RecentEventsCard />
    </div>
  );
}

function SystemCard() {
  const { t } = useLingui();
  const readiness = useReadiness();
  return (
    <Card title={t`Systemstatus`} id="system-title">
      {readiness.isPending ? (
        <Loading />
      ) : readiness.isError ? (
        <LoadError error={readiness.error} onRetry={() => void readiness.refetch()} />
      ) : (
        <div className="flex flex-col gap-3">
          <div data-testid="system-state">
            <Badge tone={readiness.data.ready ? "ok" : "bad"}>{readiness.data.ready ? t`Bereit` : t`Nicht bereit`}</Badge>
          </div>
          {readiness.data.database !== "unknown" ? (
            <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2">
              <dt className="text-ink-2">{t`Datenbank`}</dt>
              <dd>
                <Badge tone={readiness.data.database === "ok" ? "ok" : "bad"}>{readiness.data.database === "ok" ? t`In Ordnung` : t`Nicht erreichbar`}</Badge>
              </dd>
              <dt className="text-ink-2">{t`Einstellungen live`}</dt>
              <dd>
                <Badge tone={readiness.data.listener === "ok" ? "ok" : "bad"}>{readiness.data.listener === "ok" ? t`In Ordnung` : t`Nicht erreichbar`}</Badge>
              </dd>
            </dl>
          ) : (
            <p className="text-ink-2">{t`Der Server meldet sich nicht bereit. Welcher Teil fehlt, sagt die Seite „System“ unter Einstellungen.`}</p>
          )}
        </div>
      )}
    </Card>
  );
}

function InstancesCard() {
  const { t } = useLingui();
  const instances = useProviders();
  return (
    <Card
      title={t`Instanzen`}
      id="instances-title"
      aside={
        <Link to="/providers" className={TEXT_LINK}>
          {t`Zu den Anbietern`}
        </Link>
      }
    >
      {instances.isPending ? (
        <Loading />
      ) : instances.isError ? (
        <LoadError error={instances.error} onRetry={() => void instances.refetch()} />
      ) : instances.data.length === 0 ? (
        <EmptyNote>{t`Es gibt noch keine Instanz.`}</EmptyNote>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {instances.data.map((instance: ProviderInstance) => (
            <li key={instance.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
              <span className="min-w-0 font-semibold break-words">{instance.name}</span>
              <ProviderStatusBadge instance={instance} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function RecentEventsCard() {
  const { t } = useLingui();
  const instances = useProviders();
  const events = useQuery({
    queryKey: ["events", "recent"],
    queryFn: () => apiFetch<EventPage>(`/api/v1/events?limit=${RECENT_EVENTS}`),
    refetchInterval: LIVE_POLL_MS,
  });
  const names = new Map((instances.data ?? []).map((instance) => [instance.id, instance.name]));
  return (
    <Card
      title={t`Letzte Ereignisse`}
      id="events-title"
      aside={
        <Link to="/protocol" className={TEXT_LINK}>
          {t`Zum Protokoll`}
        </Link>
      }
    >
      {events.isPending ? (
        <Loading />
      ) : events.isError ? (
        <LoadError error={events.error} onRetry={() => void events.refetch()} />
      ) : events.data.items.length === 0 ? (
        <EmptyNote>{t`Noch keine Ereignisse.`}</EmptyNote>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {events.data.items.map((event) => (
            <li key={event.id} className="flex flex-col gap-1 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Code>{event.type}</Code>
                <DeliveryBadge status={event.delivery_status} />
              </div>
              <p className="text-small break-words text-ink-2">
                {formatDateTime(event.occurred_at)} · {event.source_instance_id ? (names.get(event.source_instance_id) ?? t`Gelöschte Instanz`) : t`BambuBridge`}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
