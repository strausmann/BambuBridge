import { useLingui } from "@lingui/react/macro";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Checkbox, Input, Label, TextField } from "react-aria-components";
import { ApiError, apiFetch } from "../../api/client";
import { useDirtyGuard } from "../../app/dirtyGuard";
import { ErrorNote } from "../../shell/AuthScreen";
import { BusyButton } from "../../shell/Busy";
import { AppComboBox } from "../../shell/overlays/AppComboBox";
import { AppSheet } from "../../shell/overlays/AppSheet";
import { FIELD, FOCUS, PRIMARY_BUTTON, SECONDARY_BUTTON } from "../../shell/ui";
import { PROVIDERS_KEY, field, type ProbeResult, type ProviderInstance, type ProviderType } from "../common/api";
import { Badge, useErrorText } from "../common/ui";
import { SchemaForm, schemaDefaults, schemaErrors, schemaFields, type ConfigValue, type SecretState } from "./SchemaForm";

const typeKey = (type: Pick<ProviderType, "kind" | "type_name">) => `${type.kind}/${type.type_name}`;

interface Props {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  types: ProviderType[];
  /** Set: change this instance. Unset: make a new one (the type is picked first). */
  instance?: ProviderInstance;
}

/**
 * The sheet that makes or changes an instance: name, switch, the type's own settings (drawn from
 * its schema), a connection test with the unsaved values, and save. Secrets are write-only.
 */
export function ProviderForm({ isOpen, onOpenChange, types, instance }: Props) {
  const { t } = useLingui();
  const [picked, setPicked] = useState<string | null>(null);
  const type = instance ? types.find((candidate) => candidate.kind === instance.kind && candidate.type_name === instance.type_name) : types.find((candidate) => typeKey(candidate) === picked);
  const title = instance ? t`Instanz bearbeiten` : t`Instanz hinzufügen`;
  const options = types.map((candidate) => ({ id: typeKey(candidate), label: `${candidate.type_name} (${candidate.kind})` }));
  return (
    <AppSheet isOpen={isOpen} onOpenChange={onOpenChange} title={title}>
      {instance === undefined ? (
        <AppComboBox label={t`Typ`} options={options} selectedKey={picked} onSelectionChange={setPicked} emptyText={t`Kein Typ passt.`} />
      ) : null}
      {type ? (
        // A new key per type or instance: the form starts from that type's defaults every time.
        <Fields key={instance?.id ?? typeKey(type)} type={type} instance={instance} onDone={() => onOpenChange(false)} />
      ) : instance ? (
        <ErrorNote>{t`Der Typ dieser Instanz ist in diesem Server nicht vorhanden.`}</ErrorNote>
      ) : null}
    </AppSheet>
  );
}

function Fields({ type, instance, onDone }: { type: ProviderType; instance?: ProviderInstance; onDone: () => void }) {
  const { t } = useLingui();
  const queryClient = useQueryClient();
  const errorText = useErrorText();
  const schema = type.config_schema;
  const initialConfig = useMemo<ConfigValue>(() => (instance ? { ...instance.config } : schemaDefaults(schema)), [instance, schema]);
  const [name, setName] = useState(instance?.name ?? "");
  const [enabled, setEnabled] = useState(instance?.enabled ?? true);
  const [config, setConfig] = useState<ConfigValue>(initialConfig);
  const [unreadable, setUnreadable] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [probe, setProbe] = useState<ProbeResult | null>(null);

  const dirty = name !== (instance?.name ?? "") || enabled !== (instance?.enabled ?? true) || JSON.stringify(config) !== JSON.stringify(initialConfig);
  useDirtyGuard(dirty);

  const secretState: Record<string, SecretState> = Object.fromEntries(
    schemaFields(schema)
      .filter((spec) => spec.spec.kind === "string" && spec.spec.secret)
      .map((spec): [string, SecretState] => {
        const stored = field(instance?.secrets, spec.name)?.set === true;
        return [spec.name, stored ? (unreadable ? "reenter" : "set") : "unset"];
      }),
  );

  const explain = (error: unknown): string => {
    if (error instanceof ApiError) {
      if (error.code === "provider_name_taken") return t`Dieser Name ist schon vergeben.`;
      if (error.code === "secret_undecryptable") return t`Ein gespeichertes Geheimnis lässt sich nicht mehr lesen. Gib es neu ein.`;
      if (error.code === "secret_required") return t`Ein Geheimnis fehlt. Gib es ein.`;
    }
    return errorText(error);
  };
  const fail = (error: unknown) => {
    if (error instanceof ApiError && error.code === "secret_undecryptable") setUnreadable(true);
    setMessage(explain(error));
  };

  const save = useMutation({
    mutationFn: () =>
      instance
        ? apiFetch<ProviderInstance>(`/api/v1/providers/${encodeURIComponent(instance.id)}`, { method: "PATCH", json: { name, enabled, config } })
        : apiFetch<ProviderInstance>("/api/v1/providers", { method: "POST", json: { kind: type.kind, type_name: type.type_name, name, enabled, config } }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      onDone();
    },
    onError: fail,
  });

  const test = useMutation({
    mutationFn: () =>
      apiFetch<ProbeResult>(
        instance ? `/api/v1/providers/${encodeURIComponent(instance.id)}/test` : `/api/v1/provider-types/${encodeURIComponent(type.kind)}/${encodeURIComponent(type.type_name)}/test`,
        { method: "POST", json: { config } },
      ),
    onSuccess: setProbe,
    onError: fail,
  });

  const invalid = schemaErrors(schema, config).length > 0;
  const busy = save.isPending || test.isPending;
  const begin = () => {
    setMessage(null);
    setProbe(null);
  };

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (busy) return;
        begin();
        save.mutate();
      }}
    >
      <TextField value={name} onChange={setName} isRequired isDisabled={busy} name="name" className="flex flex-col gap-1.5">
        <Label className="font-semibold">{t`Name`}</Label>
        <Input className={FIELD} maxLength={100} autoComplete="off" />
      </TextField>
      <Checkbox isSelected={enabled} onChange={setEnabled} isDisabled={busy} className={`flex min-h-11 items-center gap-3 ${FOCUS}`}>
        <span aria-hidden="true" className="flex size-5 shrink-0 items-center justify-center rounded-r1 border border-line-strong bg-surface text-primary-ink [[data-selected]_&]:border-primary [[data-selected]_&]:bg-primary">
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" className="hidden [[data-selected]_&]:block">
            <path d="M3 8.5 6.5 12 13 4.5" />
          </svg>
        </span>
        <span className="font-semibold">{t`Aktiv`}</span>
      </Checkbox>
      <SchemaForm schema={schema} value={config} onChange={setConfig} secretState={secretState} disabled={busy} />
      {probe ? (
        <div role="status" data-testid="probe-result" className="flex flex-col items-start gap-1">
          <Badge tone={probe.ok ? "ok" : "bad"}>{probe.ok ? t`Verbindung in Ordnung` : t`Verbindung fehlgeschlagen`}</Badge>
          <p className="text-small break-words text-ink-2">
            {probe.message} · {t`${probe.duration_ms} ms`}
          </p>
        </div>
      ) : null}
      {message ? <ErrorNote>{message}</ErrorNote> : null}
      <div className="flex flex-wrap justify-end gap-3">
        <BusyButton
          busy={test.isPending}
          isDisabled={busy || invalid}
          onPress={() => {
            begin();
            test.mutate();
          }}
          className={SECONDARY_BUTTON}
        >
          {t`Verbindung testen`}
        </BusyButton>
        <BusyButton type="submit" busy={save.isPending} isDisabled={busy || invalid || name.trim() === ""} className={PRIMARY_BUTTON}>
          {t`Speichern`}
        </BusyButton>
      </div>
    </form>
  );
}
