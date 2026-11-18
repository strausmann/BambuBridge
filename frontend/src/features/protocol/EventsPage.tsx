import { useLingui } from "@lingui/react/macro";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "react-aria-components";
import { apiFetch } from "../../api/client";
import { BusyButton } from "../../shell/Busy";
import { SECONDARY_BUTTON } from "../../shell/ui";
import { LIVE_POLL_MS, useProviderTypes, useProviders, type EventPage } from "../common/api";
import { formatDateTime, localInputToIso } from "../common/format";
import { Code, EmptyNote, LoadError, Loading } from "../common/ui";
import { DeliveryBadge, useDeliveryLabel } from "./EventBadge";
import { EventDetail } from "./EventDetail";
import { FilterBar, SelectFilter, TimeRangeFilter, type TimeRange } from "./FilterBar";

const PAGE_SIZE = 50;

interface Filters {
  range: TimeRange;
  source: string;
  type: string;
  status: string;
}

const NONE: Filters = { range: { from: "", to: "" }, source: "", type: "", status: "" };

export function eventsQuery(filters: Filters, cursor: string | null): string {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
  const from = localInputToIso(filters.range.from);
  const to = localInputToIso(filters.range.to);
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  if (filters.source) params.set("source", filters.source);
  if (filters.type) params.set("type", filters.type);
  if (filters.status) params.set("status", filters.status);
  if (cursor) params.set("cursor", cursor);
  return `/api/v1/events?${params.toString()}`;
}

export function EventsPage() {
  const { t } = useLingui();
  const deliveryLabel = useDeliveryLabel();
  const [filters, setFilters] = useState<Filters>(NONE);
  const [open, setOpen] = useState<string | null>(null);
  const instances = useProviders();
  const types = useProviderTypes();
  const names = new Map((instances.data ?? []).map((instance) => [instance.id, instance.name]));
  const typeNames = [...new Set((types.data ?? []).flatMap((type) => type.event_types.map((event) => event.name)))].sort();

  const events = useInfiniteQuery({
    queryKey: ["events", "list", filters],
    queryFn: ({ pageParam }) => apiFetch<EventPage>(eventsQuery(filters, pageParam)),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    refetchInterval: LIVE_POLL_MS,
  });
  const items = events.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div className="flex flex-col gap-4">
      <FilterBar label={t`Ereignisse filtern`}>
        <TimeRangeFilter value={filters.range} onChange={(range) => setFilters({ ...filters, range })} />
        <SelectFilter label={t`Quelle`} anyLabel={t`Alle Quellen`} value={filters.source} onChange={(source) => setFilters({ ...filters, source })} options={(instances.data ?? []).map((instance) => ({ value: instance.id, label: instance.name }))} />
        <SelectFilter label={t`Ereignistyp`} anyLabel={t`Alle Typen`} value={filters.type} onChange={(type) => setFilters({ ...filters, type })} options={typeNames.map((name) => ({ value: name, label: name }))} />
        <SelectFilter
          label={t`Zustellung`}
          anyLabel={t`Alle`}
          value={filters.status}
          onChange={(status) => setFilters({ ...filters, status })}
          options={(["done", "pending", "failed"] as const).map((status) => ({ value: status, label: deliveryLabel(status) }))}
        />
      </FilterBar>

      {events.isPending ? (
        <Loading />
      ) : events.isError ? (
        <LoadError error={events.error} onRetry={() => void events.refetch()} />
      ) : items.length === 0 ? (
        <EmptyNote>{JSON.stringify(filters) === JSON.stringify(NONE) ? t`Noch keine Ereignisse.` : t`Keine Ereignisse für diese Filter.`}</EmptyNote>
      ) : (
        <ul aria-label={t`Ereignisse`} className="flex flex-col divide-y divide-line overflow-hidden rounded-r3 border border-line bg-surface">
          {items.map((event) => (
            <li key={event.id}>
              <Button onPress={() => setOpen(event.id)} aria-label={`${event.type}, ${formatDateTime(event.occurred_at)}`} className="press flex min-h-14 w-full min-w-0 flex-col gap-1 px-4 py-3 text-left hover:bg-sunken">
                <span className="flex flex-wrap items-center justify-between gap-2">
                  <Code>{event.type}</Code>
                  <DeliveryBadge status={event.delivery_status} />
                </span>
                <span className="text-small break-words text-ink-2">
                  {formatDateTime(event.occurred_at)} · {event.source_instance_id ? (names.get(event.source_instance_id) ?? t`Gelöschte Instanz`) : t`BambuBridge`}
                </span>
              </Button>
            </li>
          ))}
        </ul>
      )}
      {events.hasNextPage ? (
        <BusyButton busy={events.isFetchingNextPage} isDisabled={events.isFetchingNextPage} onPress={() => void events.fetchNextPage()} className={`${SECONDARY_BUTTON} self-center`}>
          {t`Ältere laden`}
        </BusyButton>
      ) : null}
      {open ? <EventDetail eventId={open} sourceName={(id) => (id ? (names.get(id) ?? t`Gelöschte Instanz`) : t`BambuBridge`)} onClose={() => setOpen(null)} /> : null}
    </div>
  );
}
