import { useLingui } from "@lingui/react/macro";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "react-aria-components";
import { apiFetch } from "../../api/client";
import { BusyButton } from "../../shell/Busy";
import { AppSheet } from "../../shell/overlays/AppSheet";
import { SECONDARY_BUTTON } from "../../shell/ui";
import { LIVE_POLL_MS, useProviders, type CommunicationDetailData, type CommunicationPage as Page, type CommunicationSummary } from "../common/api";
import { formatDateTime, localInputToIso, prettyJson } from "../common/format";
import { Badge, Code, DataBlock, EmptyNote, LoadError, Loading } from "../common/ui";
import { FilterBar, SelectFilter, TimeRangeFilter, type TimeRange } from "./FilterBar";

const PAGE_SIZE = 50;

interface Filters {
  range: TimeRange;
  instance: string;
  status: string;
}
const NONE: Filters = { range: { from: "", to: "" }, instance: "", status: "" };

export function communicationQuery(filters: Filters, cursor: string | null): string {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
  const from = localInputToIso(filters.range.from);
  const to = localInputToIso(filters.range.to);
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  if (filters.instance) params.set("instance", filters.instance);
  if (filters.status) params.set("status", filters.status);
  if (cursor) params.set("cursor", cursor);
  return `/api/v1/communication?${params.toString()}`;
}

function StatusBadge({ entry }: { entry: Pick<CommunicationSummary, "status" | "error"> }) {
  const { t } = useLingui();
  if (entry.status === null) return <Badge tone="bad">{entry.error ? t`Keine Antwort` : t`Ohne Antwort`}</Badge>;
  const tone = entry.status < 300 ? "ok" : entry.status < 400 ? "info" : entry.status < 500 ? "warn" : "bad";
  return <Badge tone={tone}>{entry.status}</Badge>;
}

/** The calls instances make to the outside and receive from it, as they were stored (already masked). */
export function CommunicationPage() {
  const { t } = useLingui();
  const [filters, setFilters] = useState<Filters>(NONE);
  const [open, setOpen] = useState<string | null>(null);
  const instances = useProviders();
  const names = new Map((instances.data ?? []).map((instance) => [instance.id, instance.name]));
  const log = useInfiniteQuery({
    queryKey: ["communication", "list", filters],
    queryFn: ({ pageParam }) => apiFetch<Page>(communicationQuery(filters, pageParam)),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    refetchInterval: LIVE_POLL_MS,
  });
  const items = log.data?.pages.flatMap((page) => page.items) ?? [];
  const unfiltered = JSON.stringify(filters) === JSON.stringify(NONE);
  return (
    <div className="flex flex-col gap-4">
      <FilterBar label={t`Kommunikation filtern`}>
        <TimeRangeFilter value={filters.range} onChange={(range) => setFilters({ ...filters, range })} />
        <SelectFilter label={t`Instanz`} anyLabel={t`Alle Instanzen`} value={filters.instance} onChange={(instance) => setFilters({ ...filters, instance })} options={(instances.data ?? []).map((instance) => ({ value: instance.id, label: instance.name }))} />
        <SelectFilter
          label={t`Antwort`}
          anyLabel={t`Alle`}
          value={filters.status}
          onChange={(status) => setFilters({ ...filters, status })}
          options={[
            { value: "2xx", label: "2xx" },
            { value: "3xx", label: "3xx" },
            { value: "4xx", label: "4xx" },
            { value: "5xx", label: "5xx" },
            { value: "none", label: t`Ohne Antwort` },
          ]}
        />
      </FilterBar>
      {log.isPending ? (
        <Loading />
      ) : log.isError ? (
        <LoadError error={log.error} onRetry={() => void log.refetch()} />
      ) : items.length === 0 ? (
        <EmptyNote>{unfiltered ? t`Noch keine Kommunikation.` : t`Keine Einträge für diese Filter.`}</EmptyNote>
      ) : (
        <ul aria-label={t`Kommunikation`} className="flex flex-col divide-y divide-line overflow-hidden rounded-r3 border border-line bg-surface">
          {items.map((entry) => (
            <li key={entry.id}>
              <Button onPress={() => setOpen(entry.id)} aria-label={`${entry.method} ${entry.target}, ${formatDateTime(entry.occurred_at)}`} className="press flex min-h-14 w-full min-w-0 flex-col gap-1 px-4 py-3 text-left hover:bg-sunken">
                <span className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0">
                    <span className="font-semibold">{entry.method}</span> <Code>{entry.target}</Code>
                  </span>
                  <StatusBadge entry={entry} />
                </span>
                <span className="text-small break-words text-ink-2">
                  {formatDateTime(entry.occurred_at)} · {names.get(entry.instance_id) ?? t`Gelöschte Instanz`} · {entry.direction === "outbound" ? t`ausgehend` : t`eingehend`} · {t`${entry.duration_ms} ms`}
                </span>
              </Button>
            </li>
          ))}
        </ul>
      )}
      {log.hasNextPage ? (
        <BusyButton busy={log.isFetchingNextPage} isDisabled={log.isFetchingNextPage} onPress={() => void log.fetchNextPage()} className={`${SECONDARY_BUTTON} self-center`}>
          {t`Ältere laden`}
        </BusyButton>
      ) : null}
      {open ? <CommunicationDetail entryId={open} onClose={() => setOpen(null)} /> : null}
    </div>
  );
}

function CommunicationDetail({ entryId, onClose }: { entryId: string; onClose: () => void }) {
  const { t } = useLingui();
  const detail = useQuery({ queryKey: ["communication", "detail", entryId], queryFn: () => apiFetch<CommunicationDetailData>(`/api/v1/communication/${encodeURIComponent(entryId)}`) });
  return (
    <AppSheet
      isOpen
      onOpenChange={(open) => !open && onClose()}
      title={t`Aufruf`}
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
        <div className="flex flex-col gap-4" data-testid="communication-detail">
          <p className="min-w-0">
            <span className="font-semibold">{detail.data.method}</span> <Code>{detail.data.target}</Code>
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge entry={detail.data} />
            <span className="text-small text-ink-2">{t`${detail.data.duration_ms} ms`}</span>
            {detail.data.truncated ? <Badge tone="warn">{t`Gekürzt`}</Badge> : null}
          </div>
          {detail.data.error ? <p className="break-words">{detail.data.error}</p> : null}
          <p className="text-small text-ink-2">{t`Zugangsdaten sind schon beim Speichern durch *** ersetzt worden.`}</p>
          <Part title={t`Anfrage: Kopfzeilen`} text={prettyJson(detail.data.request_headers)} />
          {detail.data.request_body !== null ? <Part title={t`Anfrage: Inhalt`} text={detail.data.request_body} /> : null}
          <Part title={t`Antwort: Kopfzeilen`} text={prettyJson(detail.data.response_headers)} />
          {detail.data.response_body !== null ? <Part title={t`Antwort: Inhalt`} text={detail.data.response_body} /> : null}
        </div>
      )}
    </AppSheet>
  );
}

function Part({ title, text }: { title: string; text: string }) {
  return (
    <div>
      <h3 className="mb-1 font-semibold">{title}</h3>
      <DataBlock label={title}>{text}</DataBlock>
    </div>
  );
}
