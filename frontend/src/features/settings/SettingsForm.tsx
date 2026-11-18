import { useLingui } from "@lingui/react/macro";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Button, Checkbox, Input, Label, TextField } from "react-aria-components";
import { apiFetch } from "../../api/client";
import { useDirtyGuard } from "../../app/dirtyGuard";
import { ErrorNote } from "../../shell/AuthScreen";
import { BusyButton } from "../../shell/Busy";
import { FIELD, FOCUS, PRIMARY_BUTTON, SECONDARY_BUTTON } from "../../shell/ui";
import { SETTINGS_KEY, field, useSettings, withField, type SettingView } from "../common/api";
import { LoadError, Loading, useErrorText } from "../common/ui";
import { useSettingLabel } from "./settingText";

type Draft = Record<string, unknown>;

/** A copy of the set without `key`. */
function without(set: ReadonlySet<string>, key: string): ReadonlySet<string> {
  return set.has(key) ? new Set([...set].filter((entry) => entry !== key)) : set;
}

/**
 * The value a field shows: what was changed here, else what the server has. `null` in the draft is
 * "back to the default" (that is what the save does), so the default is what is previewed.
 */
function shown(setting: SettingView, draft: Draft): unknown {
  if (!Object.hasOwn(draft, setting.key)) return setting.value;
  const drafted = field(draft, setting.key);
  return drafted === null ? setting.default : drafted;
}

/**
 * Every setting of the given sections, as a form that saves what was changed (and only that).
 * `null` in the draft means "back to the default" (for a secret: remove it).
 */
export function SettingsForm({ sections }: { sections: readonly string[] }) {
  const { t } = useLingui();
  const queryClient = useQueryClient();
  const errorText = useErrorText();
  const settings = useSettings();
  const [draft, setDraft] = useState<Draft>({});
  const [message, setMessage] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  // Fields keep the text being typed; when a change is dropped or reset they start over from the value.
  // `epoch` restarts all of them (discard all, saved); `fieldEpoch` only the one that was reset or reverted,
  // so the others keep what is typed in them and what `blank` says about it.
  const [epoch, setEpoch] = useState(0);
  const [fieldEpoch, setFieldEpoch] = useState<ReadonlyMap<string, number>>(new Map());
  const restartField = (key: string) => setFieldEpoch((current) => new Map(current).set(key, (current.get(key) ?? 0) + 1));
  // Number fields that hold no whole number right now. An empty field is no value: saving waits until it is filled.
  const [blank, setBlank] = useState<ReadonlySet<string>>(new Set());
  const blocked = blank.size > 0;
  useDirtyGuard(Object.keys(draft).length > 0 || blocked);

  const save = useMutation({
    mutationFn: () => apiFetch<void>("/api/v1/settings", { method: "PUT", json: { values: draft } }),
    onMutate: () => {
      setMessage(null);
      setSaved(false);
    },
    onSuccess: async () => {
      // The fields start over from the stored values only once those are the new ones: a remount
      // before the refresh is through would show the old value next to the "saved" message.
      await queryClient.invalidateQueries({ queryKey: SETTINGS_KEY });
      setDraft({});
      setBlank(new Set());
      setEpoch((n) => n + 1);
      setSaved(true);
    },
    onError: (error) => setMessage(errorText(error)),
  });

  if (settings.isPending) return <Loading />;
  if (settings.isError) return <LoadError error={settings.error} onRetry={() => void settings.refetch()} />;
  const own = settings.data.filter((setting) => sections.includes(setting.section));
  const change = (key: string, value: unknown) => {
    setSaved(false);
    setDraft((current) => withField<unknown>(current, key, value));
    if (value === null) {
      setBlank((current) => without(current, key));
      restartField(key);
    }
  };
  /** A number field holds no whole number (`true`: emptied or half typed) or holds one again (`false`). */
  const setBlankField = (key: string, empty: boolean) => setBlank((current) => (current.has(key) === empty ? current : empty ? new Set(current).add(key) : without(current, key)));
  /** Back to what is stored: drops the change of one field. */
  const revert = (key: string) => {
    setDraft((current) => withField<unknown>(current, key, undefined));
    setBlank((current) => without(current, key));
    restartField(key);
  };

  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (!save.isPending && !blocked && Object.keys(draft).length > 0) save.mutate();
      }}
    >
      {own.length === 0 ? <p className="text-ink-2">{t`Hier gibt es keine Einstellungen.`}</p> : null}
      {own.map((setting) => (
        <SettingField key={`${setting.key}:${epoch}:${fieldEpoch.get(setting.key) ?? 0}`} setting={setting} draft={draft} onChange={change} onRevert={revert} onBlank={setBlankField} disabled={save.isPending} />
      ))}
      {message ? <ErrorNote>{message}</ErrorNote> : null}
      {saved ? (
        <p role="status" className="rounded-r2 bg-ok-soft px-3 py-2">
          {t`Gespeichert. Die Änderung gilt ohne Neustart.`}
        </p>
      ) : null}
      <div className="flex flex-wrap justify-end gap-3">
        <Button isDisabled={(Object.keys(draft).length === 0 && !blocked) || save.isPending} onPress={() => {
            setDraft({});
            setBlank(new Set());
            setEpoch((n) => n + 1);
          }}
          className={SECONDARY_BUTTON}
        >
          {t`Änderungen verwerfen`}
        </Button>
        <BusyButton type="submit" busy={save.isPending} isDisabled={Object.keys(draft).length === 0 || blocked || save.isPending} className={PRIMARY_BUTTON}>
          {t`Speichern`}
        </BusyButton>
      </div>
    </form>
  );
}

interface FieldProps {
  setting: SettingView;
  draft: Draft;
  onChange: (key: string, value: unknown) => void;
  onRevert: (key: string) => void;
  disabled: boolean;
}

function SettingField({ setting, draft, onChange, onRevert, onBlank, disabled }: FieldProps & { onBlank: (key: string, empty: boolean) => void }) {
  const { t } = useLingui();
  const label = useSettingLabel()(setting.key);
  const value = shown(setting, draft);
  const changed = Object.hasOwn(draft, setting.key);
  const range = setting.min != null && setting.max != null ? t`Zwischen ${setting.min} und ${setting.max}` : undefined;
  const reset = changed ? (
    <Button onPress={() => onRevert(setting.key)} isDisabled={disabled} className={`${SECONDARY_BUTTON} self-start`}>
      {t`Änderung verwerfen`}
    </Button>
  ) : setting.set && setting.type !== "secret" ? (
    <Button onPress={() => onChange(setting.key, null)} isDisabled={disabled} className={`${SECONDARY_BUTTON} self-start`} aria-label={t`${label}: auf Standard zurücksetzen`}>
      {t`Auf Standard zurücksetzen`}
    </Button>
  ) : null;

  switch (setting.type) {
    case "int":
      return (
        <IntSetting setting={setting} label={label} value={value} range={range} reset={reset} disabled={disabled} onChange={(n) => onChange(setting.key, n)} onBlank={(empty) => onBlank(setting.key, empty)} />
      );
    case "bool":
      return (
        <div className="flex flex-col gap-1.5">
          <Checkbox isSelected={value === true} onChange={(on) => onChange(setting.key, on)} isDisabled={disabled} className={`flex min-h-11 items-center gap-3 ${FOCUS}`}>
            <span className="font-semibold">{label}</span>
          </Checkbox>
          {reset}
        </div>
      );
    case "secret":
      return <SecretSetting setting={setting} label={label} draft={draft} onChange={onChange} onRevert={onRevert} disabled={disabled} />;
    case "choice":
      return <ChoiceSetting setting={setting} label={label} value={value} onChange={(v) => onChange(setting.key, v)} reset={reset} disabled={disabled} />;
    case "choices":
      return <ChoicesSetting setting={setting} label={label} value={value} onChange={(v) => onChange(setting.key, v)} reset={reset} disabled={disabled} />;
    default:
      return (
        <div className="flex flex-col gap-1.5">
          <TextField value={typeof value === "string" ? value : String(setting.default ?? "")} onChange={(text) => onChange(setting.key, text)} isDisabled={disabled} type={setting.type === "url" ? "url" : "text"} name={setting.key} className="flex flex-col gap-1.5">
            <Label className="font-semibold">{label}</Label>
            <Input className={FIELD} spellCheck={false} autoCapitalize="none" autoCorrect="off" />
          </TextField>
          {reset}
        </div>
      );
  }
}

/**
 * A number field that may be empty while it is typed in: only a whole number is handed on, so
 * clearing the field to type a new value does not put the old one back under the cursor.
 */
function IntSetting({ setting, label, value, range, reset, disabled, onChange, onBlank }: { setting: SettingView; label: string; value: unknown; range: string | undefined; reset: React.ReactNode; disabled: boolean; onChange: (n: number) => void; onBlank: (empty: boolean) => void }) {
  const { t } = useLingui();
  const [text, setText] = useState(value === null || value === undefined ? String(setting.default ?? "") : String(value));
  const notWhole = text.trim() === "" || !Number.isInteger(Number(text));
  return (
    <div className="flex flex-col gap-1.5">
      <TextField
        value={text}
        onChange={(next) => {
          setText(next);
          const parsed = Number(next);
          const whole = next.trim() !== "" && Number.isInteger(parsed);
          onBlank(!whole);
          if (whole) onChange(parsed);
        }}
        isInvalid={notWhole}
        type="number"
        isDisabled={disabled}
        name={setting.key}
        className="flex flex-col gap-1.5"
      >
        <Label className="font-semibold">{label}</Label>
        <Input className={FIELD} inputMode="numeric" min={setting.min ?? undefined} max={setting.max ?? undefined} step={1} />
      </TextField>
      {range ? <p className="text-small text-ink-2">{range}</p> : null}
      {notWhole ? <p className="text-small font-semibold text-bad">{t`Bitte eine ganze Zahl eingeben.`}</p> : null}
      {reset}
    </div>
  );
}

function SecretSetting({ setting, label, draft, onChange, onRevert, disabled }: FieldProps & { label: string }) {
  const { t } = useLingui();
  const entered = Object.hasOwn(draft, setting.key) ? field(draft, setting.key) : undefined;
  const removing = Object.hasOwn(draft, setting.key) && entered === null;
  const state = setting.undecryptable ? t`neu eingeben nötig` : setting.set ? t`gesetzt` : t`nicht gesetzt`;
  return (
    <div className="flex flex-col gap-1.5">
      <TextField
        value={typeof entered === "string" ? entered : ""}
        onChange={(text) => (text === "" ? onRevert(setting.key) : onChange(setting.key, text))}
        isDisabled={disabled || removing}
        type="password"
        autoComplete="new-password"
        name={setting.key}
        className="flex flex-col gap-1.5"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <Label className="font-semibold">{label}</Label>
          <span data-testid={`secret-state-${setting.key}`} className={`text-small font-semibold ${setting.undecryptable ? "text-bad" : "text-ink-2"}`}>
            {removing ? t`wird entfernt` : state}
          </span>
        </div>
        <Input className={`${FIELD} font-mono`} spellCheck={false} autoCapitalize="none" autoCorrect="off" placeholder={setting.set ? t`Leer lassen, um den gespeicherten Wert zu behalten` : undefined} />
      </TextField>
      {removing ? (
        <Button onPress={() => onRevert(setting.key)} isDisabled={disabled} className={`${SECONDARY_BUTTON} self-start`}>
          {t`Entfernen abbrechen`}
        </Button>
      ) : setting.set || setting.undecryptable ? (
        <Button onPress={() => onChange(setting.key, null)} isDisabled={disabled} className={`${SECONDARY_BUTTON} self-start`} aria-label={t`${label}: entfernen`}>
          {t`Entfernen`}
        </Button>
      ) : null}
    </div>
  );
}

function ChoiceSetting({ setting, label, value, onChange, reset, disabled }: { setting: SettingView; label: string; value: unknown; onChange: (value: string) => void; reset: React.ReactNode; disabled: boolean }) {
  const id = useId();
  const current = typeof value === "string" ? value : String(setting.default ?? "");
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="font-semibold">
        {label}
      </label>
      <select id={id} name={setting.key} value={current} disabled={disabled} onChange={(event) => onChange(event.target.value)} className={`${FIELD} appearance-auto`}>
        {(setting.choices ?? []).map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
      {reset}
    </div>
  );
}

function ChoicesSetting({ setting, label, value, onChange, reset, disabled }: { setting: SettingView; label: string; value: unknown; onChange: (value: string[]) => void; reset: React.ReactNode; disabled: boolean }) {
  const { t } = useLingui();
  const selected = Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : [];
  const choices = setting.choices ?? [];
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="font-semibold">{label}</legend>
      {choices.length === 0 ? <p className="text-ink-2">{t`Es ist kein Anmeldedienst verfügbar.`}</p> : null}
      {choices.map((choice) => (
        <Checkbox
          key={choice}
          isSelected={selected.includes(choice)}
          isDisabled={disabled}
          // The order of the list is the order they are asked in: keep it as the server has it.
          onChange={(on) => onChange(choices.filter((c) => (c === choice ? on : selected.includes(c))))}
          className={`flex min-h-11 items-center gap-3 ${FOCUS}`}
        >
          <span>{choice}</span>
        </Checkbox>
      ))}
      {selected.length === 0 && choices.length > 0 ? <p className="text-small text-ink-2">{t`Ohne Auswahl ist die Anmeldung über Kopfzeilen aus.`}</p> : null}
      {reset}
    </fieldset>
  );
}
