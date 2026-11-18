import { useLingui } from "@lingui/react/macro";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "react-aria-components";
import { apiFetch } from "../../api/client";
import { ErrorNote } from "../../shell/AuthScreen";
import { BusyButton } from "../../shell/Busy";
import { AppDialog } from "../../shell/overlays/AppDialog";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "../../shell/ui";
import { PROVIDERS_KEY, useProviderTypes, useProviders, type ProbeResult, type ProviderInstance, type ProviderType } from "../common/api";
import { formatDateTime, prettyJson } from "../common/format";
import { Badge, Card, Code, DataBlock, EmptyNote, LoadError, Loading, PageTitle, useErrorText } from "../common/ui";
import { ProviderForm } from "./ProviderForm";
import { ProviderStatusBadge } from "./ProviderStatusBadge";
import { schemaFields, SchemaForm, schemaDefaults, type ConfigValue, type JsonSchema } from "./SchemaForm";

type Action = ProviderType["actions"][number];

export function ProvidersPage() {
  const { t } = useLingui();
  const instances = useProviders();
  const types = useProviderTypes();
  const [form, setForm] = useState<{ instance?: ProviderInstance } | null>(null);
  const [removing, setRemoving] = useState<ProviderInstance | null>(null);

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <PageTitle
        aside={
          <Button onPress={() => setForm({})} isDisabled={!types.data} className={PRIMARY_BUTTON}>
            {t`Instanz hinzufügen`}
          </Button>
        }
      >
        {t`Anbieter`}
      </PageTitle>

      <Card title={t`Instanzen`} id="instances-title">
        {instances.isPending ? (
          <Loading />
        ) : instances.isError ? (
          <LoadError error={instances.error} onRetry={() => void instances.refetch()} />
        ) : instances.data.length === 0 ? (
          <EmptyNote>{t`Es gibt noch keine Instanz. Lege mit „Instanz hinzufügen“ die erste an.`}</EmptyNote>
        ) : (
          <ul className="flex flex-col gap-3">
            {instances.data.map((instance) => (
              <li key={instance.id}>
                <InstanceCard instance={instance} type={types.data?.find((c) => c.kind === instance.kind && c.type_name === instance.type_name)} onEdit={() => setForm({ instance })} onRemove={() => setRemoving(instance)} />
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={t`Verfügbare Typen`} id="types-title">
        {types.isPending ? <Loading /> : types.isError ? <LoadError error={types.error} onRetry={() => void types.refetch()} /> : types.data.length === 0 ? <EmptyNote>{t`Dieser Server kennt keine Anbietertypen.`}</EmptyNote> : <ul className="flex flex-col gap-3">{types.data.map((type) => <li key={`${type.kind}/${type.type_name}`}><TypeCard type={type} /></li>)}</ul>}
      </Card>

      {/* Mounted only while open: every opening starts from the stored state. */}
      {form && types.data ? <ProviderForm isOpen onOpenChange={(open) => !open && setForm(null)} types={types.data} instance={form.instance} /> : null}
      {removing ? <RemoveDialog instance={removing} onClose={() => setRemoving(null)} /> : null}
    </div>
  );
}

function InstanceCard({ instance, type, onEdit, onRemove }: { instance: ProviderInstance; type: ProviderType | undefined; onEdit: () => void; onRemove: () => void }) {
  const { t } = useLingui();
  const queryClient = useQueryClient();
  const errorText = useErrorText();
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [runnable, setRunnable] = useState<Action | null>(null);

  const test = useMutation({
    mutationFn: () => apiFetch<ProbeResult>(`/api/v1/providers/${encodeURIComponent(instance.id)}/test`, { method: "POST", json: { config: {} } }),
    onMutate: () => {
      setProbe(null);
      setFailure(null);
    },
    onSuccess: setProbe,
    onError: (error) => setFailure(errorText(error)),
  });
  const toggle = useMutation({
    mutationFn: () => apiFetch<ProviderInstance>(`/api/v1/providers/${encodeURIComponent(instance.id)}`, { method: "PATCH", json: { enabled: !instance.enabled } }),
    onMutate: () => setFailure(null),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY }),
    onError: (error) => setFailure(errorText(error)),
  });

  return (
    <article aria-label={instance.name} className="flex min-w-0 flex-col gap-3 rounded-r2 border border-line p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-body font-semibold break-words">{instance.name}</h3>
          <p className="text-small text-ink-2">
            <Code>{`${instance.type_name} · ${instance.kind}`}</Code>
          </p>
        </div>
        <ProviderStatusBadge instance={instance} />
      </div>
      {instance.status.message ? <p className="text-small break-words text-ink-2">{instance.status.message}</p> : null}
      <p className="text-small text-ink-3">{t`Status seit ${formatDateTime(instance.status.since)}`}</p>
      {probe ? (
        <div role="status" className="flex flex-col items-start gap-1">
          <Badge tone={probe.ok ? "ok" : "bad"}>{probe.ok ? t`Verbindung in Ordnung` : t`Verbindung fehlgeschlagen`}</Badge>
          <p className="text-small break-words text-ink-2">{probe.message}</p>
        </div>
      ) : null}
      {failure ? <ErrorNote>{failure}</ErrorNote> : null}
      <div className="flex flex-wrap gap-2">
        <Button onPress={onEdit} className={SECONDARY_BUTTON}>
          {t`Bearbeiten`}
        </Button>
        <BusyButton busy={test.isPending} isDisabled={test.isPending} onPress={() => test.mutate()} className={SECONDARY_BUTTON}>
          {t`Verbindung testen`}
        </BusyButton>
        {type?.actions.map((action) => (
          <Button key={action.name} isDisabled={!instance.enabled} onPress={() => setRunnable(action)} className={SECONDARY_BUTTON}>
            {t`Aktion „${action.name}“`}
          </Button>
        ))}
        <BusyButton busy={toggle.isPending} isDisabled={toggle.isPending} onPress={() => toggle.mutate()} className={SECONDARY_BUTTON}>
          {instance.enabled ? t`Deaktivieren` : t`Aktivieren`}
        </BusyButton>
        <Button onPress={onRemove} className={SECONDARY_BUTTON}>
          {t`Löschen`}
        </Button>
      </div>
      {runnable ? <ActionDialog instance={instance} action={runnable} onClose={() => setRunnable(null)} /> : null}
    </article>
  );
}

/** Runs one action of a running instance; asks for its parameters first when the schema has any. */
function ActionDialog({ instance, action, onClose }: { instance: ProviderInstance; action: Action; onClose: () => void }) {
  const { t } = useLingui();
  const errorText = useErrorText();
  const schema = action.params_schema as JsonSchema;
  const hasParams = schemaFields(schema).length > 0;
  const [params, setParams] = useState<ConfigValue>(schemaDefaults(schema));
  const [result, setResult] = useState<unknown>(undefined);
  const [failure, setFailure] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: () => apiFetch<{ result: unknown }>(`/api/v1/providers/${encodeURIComponent(instance.id)}/actions/${encodeURIComponent(action.name)}`, { method: "POST", json: { params } }),
    onMutate: () => {
      setFailure(null);
      setResult(undefined);
    },
    onSuccess: (done) => setResult(done.result),
    onError: (error) => setFailure(errorText(error)),
  });
  return (
    <AppDialog
      isOpen
      onOpenChange={(open) => !open && onClose()}
      title={t`Aktion „${action.name}“`}
      actions={
        <>
          <Button onPress={onClose} className={SECONDARY_BUTTON}>
            {t`Schließen`}
          </Button>
          <BusyButton busy={run.isPending} isDisabled={run.isPending} onPress={() => run.mutate()} className={PRIMARY_BUTTON}>
            {t`Ausführen`}
          </BusyButton>
        </>
      }
    >
      <p className="text-ink-2 break-words">{t`Instanz: ${instance.name}`}</p>
      {hasParams ? <SchemaForm schema={schema} value={params} onChange={setParams} disabled={run.isPending} /> : null}
      {failure ? <ErrorNote>{failure}</ErrorNote> : null}
      {result !== undefined ? (
        <div role="status" data-testid="action-result">
          <p className="mb-1 font-semibold">{t`Ergebnis`}</p>
          <DataBlock label={t`Ergebnis der Aktion`}>{prettyJson(result)}</DataBlock>
        </div>
      ) : null}
    </AppDialog>
  );
}

function RemoveDialog({ instance, onClose }: { instance: ProviderInstance; onClose: () => void }) {
  const { t } = useLingui();
  const queryClient = useQueryClient();
  const errorText = useErrorText();
  const [failure, setFailure] = useState<string | null>(null);
  const remove = useMutation({
    mutationFn: () => apiFetch<void>(`/api/v1/providers/${encodeURIComponent(instance.id)}`, { method: "DELETE" }),
    onMutate: () => setFailure(null),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      onClose();
    },
    onError: (error) => setFailure(errorText(error)),
  });
  return (
    <AppDialog
      isOpen
      onOpenChange={(open) => !open && onClose()}
      title={t`Instanz löschen`}
      actions={
        <>
          <Button onPress={onClose} className={SECONDARY_BUTTON}>
            {t`Abbrechen`}
          </Button>
          <BusyButton busy={remove.isPending} isDisabled={remove.isPending} onPress={() => remove.mutate()} className={PRIMARY_BUTTON}>
            {t`Endgültig löschen`}
          </BusyButton>
        </>
      }
    >
      <p className="break-words">{t`Die Instanz „${instance.name}“ und ihre gespeicherten Geheimnisse werden gelöscht. Ihre bisherigen Ereignisse bleiben im Protokoll.`}</p>
      {failure ? <ErrorNote>{failure}</ErrorNote> : null}
    </AppDialog>
  );
}

function TypeCard({ type }: { type: ProviderType }) {
  const { t } = useLingui();
  return (
    <article aria-label={`${type.type_name} (${type.kind})`} className="flex min-w-0 flex-col gap-3 rounded-r2 border border-line p-4">
      <h3 className="text-body font-semibold break-words">
        {type.type_name} <span className="text-small font-normal text-ink-2">({type.kind})</span>
      </h3>
      <Section title={t`Einstellungen`}>
        <SchemaDetails label={t`Schema der Einstellungen`} schema={type.config_schema} />
      </Section>
      <Section title={t`Ereignistypen`}>
        {type.event_types.length === 0 ? (
          <p className="text-ink-2">{t`Keine.`}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {type.event_types.map((event) => (
              <li key={event.name}>
                <p>
                  <Code>{event.name}</Code> <span className="text-small text-ink-2">{t`Version ${event.schema_version}`}</span>
                </p>
                <SchemaDetails label={t`Schema der Nutzdaten von ${event.name}`} schema={event.payload_schema} />
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title={t`Aktionen`}>
        {type.actions.length === 0 ? (
          <p className="text-ink-2">{t`Keine.`}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {type.actions.map((action) => (
              <li key={action.name}>
                <p>
                  <Code>{action.name}</Code>
                </p>
                <SchemaDetails label={t`Schema der Parameter von ${action.name}`} schema={action.params_schema} />
              </li>
            ))}
          </ul>
        )}
      </Section>
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="mb-1 text-small font-semibold tracking-wide text-ink-2 uppercase">{title}</h4>
      {children}
    </div>
  );
}

function SchemaDetails({ schema, label }: { schema: JsonSchema; label: string }) {
  const { t } = useLingui();
  return (
    <details className="mt-1">
      <summary className="inline-flex min-h-11 cursor-pointer items-center text-link underline underline-offset-2">{t`Schema anzeigen`}</summary>
      <DataBlock label={label}>{prettyJson(schema)}</DataBlock>
    </details>
  );
}
