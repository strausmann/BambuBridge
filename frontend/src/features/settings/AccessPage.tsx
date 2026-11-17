import { useLingui } from "@lingui/react/macro";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Button, Input, Label, TextField } from "react-aria-components";
import { apiFetch } from "../../api/client";
import { useDirtyGuard } from "../../app/dirtyGuard";
import type { components } from "../../api/schema.gen";
import { ErrorNote } from "../../shell/AuthScreen";
import { BusyButton } from "../../shell/Busy";
import { AppDialog } from "../../shell/overlays/AppDialog";
import { AppSheet } from "../../shell/overlays/AppSheet";
import { FIELD, PRIMARY_BUTTON, SECONDARY_BUTTON } from "../../shell/ui";
import { API_KEYS_KEY, type ApiKeyRead } from "../common/api";
import { formatDateTime, localInputToIso } from "../common/format";
import { Badge, Card, Code, EmptyNote, LoadError, Loading, useErrorText } from "../common/ui";
import { SettingsForm } from "./SettingsForm";

type Created = components["schemas"]["ApiKeyCreated"];
type Scope = ApiKeyRead["scope"];
const SCOPES: readonly Scope[] = ["read", "operate", "admin"];

function useScopeLabel(): (scope: Scope) => string {
  const { t } = useLingui();
  return (scope) => (scope === "read" ? t`Lesen` : scope === "operate" ? t`Bedienen` : t`Verwalten`);
}

export function AccessPage() {
  const { t } = useLingui();
  const scopeLabel = useScopeLabel();
  const keys = useQuery({ queryKey: API_KEYS_KEY, queryFn: () => apiFetch<ApiKeyRead[]>("/api/v1/admin/api-keys") });
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);
  const [revoking, setRevoking] = useState<ApiKeyRead | null>(null);
  return (
    <>
      <Card
        title={t`API-Tokens`}
        id="tokens-title"
        aside={
          <Button onPress={() => setCreating(true)} className={PRIMARY_BUTTON}>
            {t`Token anlegen`}
          </Button>
        }
      >
        {keys.isPending ? (
          <Loading />
        ) : keys.isError ? (
          <LoadError error={keys.error} onRetry={() => void keys.refetch()} />
        ) : keys.data.length === 0 ? (
          <EmptyNote>{t`Es gibt noch kein Token.`}</EmptyNote>
        ) : (
          <ul className="flex flex-col gap-3">
            {keys.data.map((key) => (
              <li key={key.id}>
                <article aria-label={key.name} className="flex min-w-0 flex-col gap-2 rounded-r2 border border-line p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <h3 className="min-w-0 font-semibold break-words">{key.name}</h3>
                    <Badge tone={key.enabled ? "ok" : "neutral"}>{key.enabled ? scopeLabel(key.scope) : t`Deaktiviert`}</Badge>
                  </div>
                  <p className="text-small text-ink-2">
                    <Code>{`${key.prefix}…`}</Code> · {t`angelegt ${formatDateTime(key.created_at)}`}
                  </p>
                  <p className="text-small text-ink-2">{key.last_used_at ? t`zuletzt benutzt ${formatDateTime(key.last_used_at)}` : t`noch nie benutzt`}</p>
                  {key.expires_at ? <p className="text-small text-ink-2">{t`läuft ab ${formatDateTime(key.expires_at)}`}</p> : null}
                  {key.note ? <p className="text-small break-words">{key.note}</p> : null}
                  <Button onPress={() => setRevoking(key)} aria-label={t`Token „${key.name}“ entziehen`} className={`${SECONDARY_BUTTON} self-start`}>
                    {t`Entziehen`}
                  </Button>
                </article>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title={t`Anmeldung`} id="auth-title">
        <SettingsForm sections={["auth"]} />
      </Card>
      {creating ? <CreateKey onClose={() => setCreating(false)} onCreated={(made) => { setCreating(false); setCreated(made); }} /> : null}
      {created ? <TokenShown created={created} onClose={() => setCreated(null)} /> : null}
      {revoking ? <RevokeKey target={revoking} onClose={() => setRevoking(null)} /> : null}
    </>
  );
}

function CreateKey({ onClose, onCreated }: { onClose: () => void; onCreated: (created: Created) => void }) {
  const { t } = useLingui();
  const scopeLabel = useScopeLabel();
  const queryClient = useQueryClient();
  const errorText = useErrorText();
  const scopeId = useId();
  const expiryId = useId();
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [scope, setScope] = useState<Scope>("read");
  const [expires, setExpires] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  useDirtyGuard(name !== "" || note !== "");
  const create = useMutation({
    mutationFn: () =>
      apiFetch<Created>("/api/v1/admin/api-keys", {
        method: "POST",
        json: { name, scope, ...(note.trim() ? { note: note.trim() } : {}), ...(localInputToIso(expires) ? { expires_at: localInputToIso(expires) } : {}) },
      }),
    onMutate: () => setMessage(null),
    onSuccess: async (made) => {
      await queryClient.invalidateQueries({ queryKey: API_KEYS_KEY });
      onCreated(made);
    },
    onError: (error) => setMessage(errorText(error)),
  });
  return (
    <AppSheet isOpen onOpenChange={(open) => !open && onClose()} title={t`Token anlegen`}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!create.isPending) create.mutate();
        }}
      >
        <TextField value={name} onChange={setName} isRequired isDisabled={create.isPending} name="token-name" className="flex flex-col gap-1.5">
          <Label className="font-semibold">{t`Name`}</Label>
          <Input className={FIELD} maxLength={100} autoComplete="off" />
        </TextField>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={scopeId} className="font-semibold">
            {t`Berechtigung`}
          </label>
          <select id={scopeId} value={scope} disabled={create.isPending} onChange={(event) => setScope(SCOPES.find((s) => s === event.target.value) ?? "read")} className={`${FIELD} appearance-auto`}>
            {SCOPES.map((s) => (
              <option key={s} value={s}>
                {scopeLabel(s)}
              </option>
            ))}
          </select>
        </div>
        <TextField value={note} onChange={setNote} isDisabled={create.isPending} name="token-note" className="flex flex-col gap-1.5">
          <Label className="font-semibold">{t`Notiz (freiwillig)`}</Label>
          <Input className={FIELD} maxLength={500} autoComplete="off" />
        </TextField>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={expiryId} className="font-semibold">
            {t`Läuft ab (freiwillig)`}
          </label>
          <input id={expiryId} type="datetime-local" value={expires} disabled={create.isPending} onChange={(event) => setExpires(event.target.value)} className={FIELD} />
        </div>
        {message ? <ErrorNote>{message}</ErrorNote> : null}
        <div className="flex flex-wrap justify-end gap-3">
          <Button onPress={onClose} className={SECONDARY_BUTTON}>
            {t`Abbrechen`}
          </Button>
          <BusyButton type="submit" busy={create.isPending} isDisabled={create.isPending || name.trim() === ""} className={PRIMARY_BUTTON}>
            {t`Anlegen`}
          </BusyButton>
        </div>
      </form>
    </AppSheet>
  );
}

/** The plaintext of a new token: on this screen once, in no storage, gone when it is closed. */
function TokenShown({ created, onClose }: { created: Created; onClose: () => void }) {
  const { t } = useLingui();
  const [copy, setCopy] = useState<"idle" | "done" | "failed">("idle");
  return (
    <AppDialog
      isOpen
      onOpenChange={(open) => !open && onClose()}
      title={t`Neues Token`}
      actions={
        <Button onPress={onClose} className={PRIMARY_BUTTON}>
          {t`Fertig`}
        </Button>
      }
    >
      <p className="font-semibold">{t`Dieses Token wird nur jetzt angezeigt.`}</p>
      <p className="text-ink-2">{t`Kopiere es an einen sicheren Ort. Später ist nur noch der Anfang sichtbar.`}</p>
      {/* A long token must be reachable with the keyboard to be selected. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <pre data-testid="new-token" tabIndex={0} aria-label={t`Das neue Token`} className="rounded-r2 bg-sunken p-3 font-mono text-small break-all whitespace-pre-wrap select-all">
        {created.token}
      </pre>
      <Button
        onPress={() => {
          navigator.clipboard.writeText(created.token).then(
            () => setCopy("done"),
            () => setCopy("failed"),
          );
        }}
        className={`${SECONDARY_BUTTON} self-start`}
      >
        {t`In die Zwischenablage kopieren`}
      </Button>
      {copy === "done" ? <p role="status">{t`Kopiert.`}</p> : null}
      {copy === "failed" ? <ErrorNote>{t`Kopieren ging nicht. Markiere das Token und kopiere es von Hand.`}</ErrorNote> : null}
    </AppDialog>
  );
}

function RevokeKey({ target, onClose }: { target: ApiKeyRead; onClose: () => void }) {
  const { t } = useLingui();
  const queryClient = useQueryClient();
  const errorText = useErrorText();
  const [message, setMessage] = useState<string | null>(null);
  const revoke = useMutation({
    mutationFn: () => apiFetch<void>(`/api/v1/admin/api-keys/${encodeURIComponent(target.id)}`, { method: "DELETE" }),
    onMutate: () => setMessage(null),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: API_KEYS_KEY });
      onClose();
    },
    onError: (error) => setMessage(errorText(error)),
  });
  return (
    <AppDialog
      isOpen
      onOpenChange={(open) => !open && onClose()}
      title={t`Token entziehen`}
      actions={
        <>
          <Button onPress={onClose} className={SECONDARY_BUTTON}>
            {t`Abbrechen`}
          </Button>
          <BusyButton busy={revoke.isPending} isDisabled={revoke.isPending} onPress={() => revoke.mutate()} className={PRIMARY_BUTTON}>
            {t`Endgültig entziehen`}
          </BusyButton>
        </>
      }
    >
      <p className="break-words">{t`Das Token „${target.name}“ wird mit der nächsten Anfrage abgelehnt. Das lässt sich nicht rückgängig machen.`}</p>
      {message ? <ErrorNote>{message}</ErrorNote> : null}
    </AppDialog>
  );
}
