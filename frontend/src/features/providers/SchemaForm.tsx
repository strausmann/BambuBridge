import { useLingui } from "@lingui/react/macro";
import { useId } from "react";
import { Checkbox, Input, Label, Text, TextField } from "react-aria-components";
import { FIELD, FOCUS } from "../../shell/ui";
import { field, withField } from "../common/api";

/** What the form knows of a stored secret. `reenter`: it is stored but cannot be read any more. */
export type SecretState = "set" | "unset" | "reenter";

export type JsonSchema = Record<string, unknown>;
export type ConfigValue = Record<string, unknown>;

export type FieldKind =
  | { kind: "string"; secret: boolean; uri: boolean; minLength?: number; maxLength?: number }
  | { kind: "integer"; min?: number; max?: number }
  | { kind: "boolean" }
  | { kind: "enum"; options: readonly (string | number)[] }
  | { kind: "unsupported"; type: string };

export interface FieldSpec {
  name: string;
  title: string;
  required: boolean;
  description?: string;
  spec: FieldKind;
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const num = (value: unknown): number | undefined => (typeof value === "number" && Number.isFinite(value) ? value : undefined);

function describe(raw: Record<string, unknown>): FieldKind {
  const options = raw.enum;
  if (Array.isArray(options) && options.length > 0 && options.every((o) => typeof o === "string" || typeof o === "number")) {
    return { kind: "enum", options: options as (string | number)[] };
  }
  switch (raw.type) {
    case "string":
      return { kind: "string", secret: raw["x-secret"] === true, uri: raw.format === "uri", minLength: num(raw.minLength), maxLength: num(raw.maxLength) };
    case "integer":
      return { kind: "integer", min: num(raw.minimum), max: num(raw.maximum) };
    case "boolean":
      return { kind: "boolean" };
    default:
      return { kind: "unsupported", type: typeof raw.type === "string" ? raw.type : Array.isArray(raw.type) ? raw.type.join("|") : "?" };
  }
}

/** The fields of an object schema in the order the schema lists them. */
export function schemaFields(schema: JsonSchema): FieldSpec[] {
  const properties = isRecord(schema.properties) ? schema.properties : {};
  const required = new Set(Array.isArray(schema.required) ? schema.required.filter((r): r is string => typeof r === "string") : []);
  return Object.entries(properties).map(([name, raw]) => {
    const body = isRecord(raw) ? raw : {};
    return {
      name,
      title: typeof body.title === "string" ? body.title : name,
      required: required.has(name),
      description: typeof body.description === "string" ? body.description : undefined,
      spec: describe(body),
    };
  });
}

/** The defaults a schema declares, for the form of a new instance. Secrets never have one. */
export function schemaDefaults(schema: JsonSchema): ConfigValue {
  const properties = isRecord(schema.properties) ? schema.properties : {};
  const entries = Object.entries(properties).flatMap(([name, raw]): [string, unknown][] =>
    isRecord(raw) && raw["x-secret"] !== true && raw.default !== undefined ? [[name, raw.default]] : [],
  );
  return Object.fromEntries(entries);
}

interface Props {
  schema: JsonSchema;
  value: ConfigValue;
  onChange: (next: ConfigValue) => void;
  /** For each secret field of the schema; a field not named counts as not set. */
  secretState?: Record<string, SecretState>;
  disabled?: boolean;
}

/**
 * The configuration form of a provider type, drawn from its JSON schema: string, integer (with
 * minimum and maximum), boolean, enum, `format: uri` and `x-secret`. Anything else is said out
 * loud on the page, never dropped. A secret is write-only: its field starts empty, an empty field
 * sends nothing (the stored value stays), and the state of the stored value is shown beside it.
 */
export function SchemaForm({ schema, value, onChange, secretState, disabled = false }: Props) {
  const fields = schemaFields(schema);
  if (fields.length === 0) return <NoSettings />;
  return (
    <div className="flex flex-col gap-4">
      {fields.map((spec) => (
        <FieldRow key={spec.name} spec={spec} value={value} onChange={onChange} secretState={secretState} disabled={disabled} />
      ))}
    </div>
  );
}

function NoSettings() {
  const { t } = useLingui();
  return <p className="text-ink-2">{t`Dieser Typ hat keine Einstellungen.`}</p>;
}

function FieldRow({ spec, value, onChange, secretState, disabled }: { spec: FieldSpec; disabled: boolean } & Omit<Props, "schema" | "disabled">) {
  const set = (next: unknown) => onChange(withField(value, spec.name, next));
  const current = field(value, spec.name);
  const kind = spec.spec;
  switch (kind.kind) {
    case "string":
      return kind.secret ? (
        <SecretField spec={spec} state={field(secretState, spec.name) ?? "unset"} value={typeof current === "string" ? current : ""} onChange={(v) => set(v === "" ? undefined : v)} disabled={disabled} />
      ) : (
        <TextInput spec={spec} kind={kind} value={typeof current === "string" ? current : ""} onChange={(v) => set(v)} disabled={disabled} />
      );
    case "integer":
      return <IntegerInput spec={spec} kind={kind} value={typeof current === "number" ? current : undefined} onChange={set} disabled={disabled} />;
    case "boolean":
      return <BooleanInput spec={spec} value={current === true} onChange={set} disabled={disabled} />;
    case "enum":
      return <EnumInput spec={spec} options={kind.options} value={current} onChange={set} disabled={disabled} />;
    case "unsupported":
      return <Unsupported spec={spec} type={kind.type} />;
  }
}

function Title({ spec }: { spec: FieldSpec }) {
  const { t } = useLingui();
  return (
    <Label className="font-semibold">
      {spec.title}
      {spec.required ? <span className="sr-only">{t` (Pflichtfeld)`}</span> : null}
    </Label>
  );
}

function Hint({ children }: { children: string | undefined }) {
  return children ? (
    <Text slot="description" className="text-small text-ink-2">
      {children}
    </Text>
  ) : null;
}

function TextInput({ spec, kind, value, onChange, disabled }: { spec: FieldSpec; kind: Extract<FieldKind, { kind: "string" }>; value: string; onChange: (v: string) => void; disabled: boolean }) {
  return (
    <TextField value={value} onChange={onChange} isDisabled={disabled} isRequired={spec.required} type={kind.uri ? "url" : "text"} name={spec.name} className="flex flex-col gap-1.5">
      <Title spec={spec} />
      <Input className={`${FIELD} ${kind.uri ? "font-mono" : ""}`} maxLength={kind.maxLength} minLength={kind.minLength} spellCheck={false} autoCapitalize="none" autoCorrect="off" />
      <Hint>{spec.description}</Hint>
    </TextField>
  );
}

function IntegerInput({ spec, kind, value, onChange, disabled }: { spec: FieldSpec; kind: Extract<FieldKind, { kind: "integer" }>; value: number | undefined; onChange: (v: number | undefined) => void; disabled: boolean }) {
  const { t } = useLingui();
  const out = value !== undefined && ((kind.min !== undefined && value < kind.min) || (kind.max !== undefined && value > kind.max));
  const range =
    kind.min !== undefined && kind.max !== undefined ? t`Zwischen ${kind.min} und ${kind.max}` : kind.min !== undefined ? t`Mindestens ${kind.min}` : kind.max !== undefined ? t`Höchstens ${kind.max}` : undefined;
  return (
    <TextField
      value={value === undefined ? "" : String(value)}
      onChange={(text) => {
        const parsed = text.trim() === "" ? undefined : Number(text);
        onChange(parsed === undefined || !Number.isInteger(parsed) ? undefined : parsed);
      }}
      isDisabled={disabled}
      isRequired={spec.required}
      isInvalid={out}
      type="number"
      name={spec.name}
      className="flex flex-col gap-1.5"
    >
      <Title spec={spec} />
      <Input className={FIELD} inputMode="numeric" min={kind.min} max={kind.max} step={1} />
      <Hint>{[spec.description, range].filter(Boolean).join(" · ") || undefined}</Hint>
    </TextField>
  );
}

function BooleanInput({ spec, value, onChange, disabled }: { spec: FieldSpec; value: boolean; onChange: (v: boolean) => void; disabled: boolean }) {
  return (
    <Checkbox isSelected={value} onChange={onChange} isDisabled={disabled} name={spec.name} className={`flex min-h-11 items-center gap-3 ${FOCUS}`}>
      <span aria-hidden="true" className="flex size-5 shrink-0 items-center justify-center rounded-r1 border border-line-strong bg-surface text-primary-ink [[data-selected]_&]:border-primary [[data-selected]_&]:bg-primary">
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" className="hidden [[data-selected]_&]:block">
          <path d="M3 8.5 6.5 12 13 4.5" />
        </svg>
      </span>
      <span className="font-semibold">{spec.title}</span>
    </Checkbox>
  );
}

function EnumInput({ spec, options, value, onChange, disabled }: { spec: FieldSpec; options: readonly (string | number)[]; value: unknown; onChange: (v: string | number | undefined) => void; disabled: boolean }) {
  const { t } = useLingui();
  const id = useId();
  const chosen = options.findIndex((option) => option === value);
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="font-semibold">
        {spec.title}
      </label>
      <select
        id={id}
        name={spec.name}
        disabled={disabled}
        required={spec.required}
        value={chosen === -1 ? "" : String(chosen)}
        onChange={(event) => onChange(event.target.value === "" ? undefined : options[Number(event.target.value)])}
        className={`${FIELD} appearance-auto`}
      >
        <option value="">{t`Bitte wählen`}</option>
        {options.map((option, index) => (
          <option key={String(option)} value={String(index)}>
            {String(option)}
          </option>
        ))}
      </select>
      {spec.description ? <p className="text-small text-ink-2">{spec.description}</p> : null}
    </div>
  );
}

function SecretField({ spec, state, value, onChange, disabled }: { spec: FieldSpec; state: SecretState; value: string; onChange: (v: string) => void; disabled: boolean }) {
  const { t } = useLingui();
  const label = state === "set" ? t`gesetzt` : state === "reenter" ? t`neu eingeben nötig` : t`nicht gesetzt`;
  return (
    <TextField value={value} onChange={onChange} isDisabled={disabled} isRequired={spec.required && state !== "set"} type="password" name={spec.name} autoComplete="new-password" className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <Title spec={spec} />
        <span data-testid={`secret-state-${spec.name}`} data-state={state} className={`text-small font-semibold ${state === "reenter" ? "text-bad" : "text-ink-2"}`}>
          {label}
        </span>
      </div>
      <Input className={`${FIELD} font-mono`} spellCheck={false} autoCapitalize="none" autoCorrect="off" placeholder={state === "set" ? t`Leer lassen, um den gespeicherten Wert zu behalten` : undefined} />
      <Hint>{spec.description}</Hint>
    </TextField>
  );
}

function Unsupported({ spec, type }: { spec: FieldSpec; type: string }) {
  const { t } = useLingui();
  return (
    <div role="note" data-testid={`unsupported-${spec.name}`} className="rounded-r2 border border-line-strong bg-warn-soft px-3 py-2">
      <p className="font-semibold">{spec.title}</p>
      <p className="text-small">{t`Dieser Feldtyp (${type}) wird nicht unterstützt und kann hier nicht bearbeitet werden.`}</p>
    </div>
  );
}
