import { Trans, useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";
import { Button, Input, Label, TextField } from "react-aria-components";
import { ApiError } from "../api/client";
import { AuthScreen, ErrorNote } from "./AuthScreen";
import { BusyMark, useDelayedBusy } from "./Busy";
import { FIELD, PRIMARY_BUTTON, SECONDARY_BUTTON, TEXT_LINK } from "./ui";

interface Props {
  /** Creates the first admin token with the one-time bootstrap key and resolves to its plaintext. */
  onCreate: (bootstrapKey: string) => Promise<string>;
  /** Signs in with the new token. */
  onContinue: (token: string) => Promise<void>;
}

function useCreateMessage() {
  const { t } = useLingui();
  return (error: unknown): string => {
    if (!(error instanceof ApiError)) return t`Das Token konnte nicht angelegt werden.`;
    if (error.status === 0) return t`Der Server ist nicht erreichbar.`;
    if (error.status === 429) return t`Zu viele Versuche. Warte eine Minute und versuche es erneut.`;
    if (error.code === "bootstrap_closed") return t`Es gibt bereits ein Admin-Token. Melde dich damit an.`;
    if (error.status === 401) return t`Der Bootstrap-Schlüssel wurde nicht akzeptiert.`;
    return t`Das Token konnte nicht angelegt werden.`;
  };
}

/**
 * First start: the one-time bootstrap key (`BAMBUBRIDGE_BOOTSTRAP_ADMIN_KEY`) can do one thing,
 * create the first admin token. The token is shown exactly once; it lives only in this
 * component's state and is gone after "Continue" or a reload. While it is on screen and was not
 * yet used to sign in, the browser asks before the page is closed or reloaded.
 */
export function BootstrapKeyCreated({ onCreate, onContinue }: Props) {
  const { t } = useLingui();
  const messageFor = useCreateMessage();
  const [bootstrapKey, setBootstrapKey] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copy, setCopy] = useState<"idle" | "done" | "failed">("idle");
  const slow = useDelayedBusy(busy);

  const shown = created !== null;
  useEffect(() => {
    if (!shown) return;
    const ask = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", ask);
    return () => window.removeEventListener("beforeunload", ask);
  }, [shown]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (bootstrapKey === "" || busy) return;
    const sent = bootstrapKey;
    setBootstrapKey("");
    setBusy(true);
    setError(null);
    try {
      setCreated(await onCreate(sent));
    } catch (failure) {
      setError(messageFor(failure));
    } finally {
      setBusy(false);
    }
  }

  async function proceed(value: string) {
    setBusy(true);
    setError(null);
    try {
      await onContinue(value);
    } catch {
      setError(t`Die Anmeldung mit dem neuen Token ist fehlgeschlagen.`);
      setBusy(false);
    }
  }

  async function copyToken(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopy("done");
    } catch {
      setCopy("failed");
    }
  }

  if (created === null) {
    return (
      <AuthScreen>
        <div>
          <h1 className="text-title font-bold">{t`Erstes Admin-Token anlegen`}</h1>
          <p className="mt-1 text-ink-2">
            <Trans>
              Gib den Bootstrap-Schlüssel ein, den du dem Container als <code>BAMBUBRIDGE_BOOTSTRAP_ADMIN_KEY</code> mitgegeben hast. Er kann genau eines: das
              erste Admin-Token anlegen.
            </Trans>
          </p>
        </div>
        <form onSubmit={(event) => void create(event)} className="flex flex-col gap-4">
          <TextField value={bootstrapKey} onChange={setBootstrapKey} name="bootstrap-key" type="password" autoComplete="off" className="flex flex-col gap-1.5">
            <Label className="font-semibold">{t`Bootstrap-Schlüssel`}</Label>
            <Input className={`${FIELD} font-mono`} spellCheck={false} autoCapitalize="none" autoCorrect="off" enterKeyHint="go" />
          </TextField>
          {error ? <ErrorNote>{error}</ErrorNote> : null}
          <Button type="submit" isDisabled={busy} className={PRIMARY_BUTTON}>
            {t`Admin-Token anlegen`}
            <BusyMark show={slow} />
          </Button>
        </form>
        <p>
          <Link to="/sign-in" search={{ redirect: undefined }} className={TEXT_LINK}>
            {t`Zurück zur Anmeldung`}
          </Link>
        </p>
      </AuthScreen>
    );
  }

  return (
    <AuthScreen>
      <div>
        <h1 className="text-title font-bold">{t`Dein Admin-Token`}</h1>
        <p className="mt-1 flex items-start gap-2 text-ink">
          {/* The one accent on this screen: this is the only time the token is visible. */}
          <span aria-hidden="true" className="mt-1.5 size-2.5 shrink-0 rounded-full bg-accent" />
          <span>{t`Dieses Token wird nur jetzt angezeigt. Lege es in deinem Passwortmanager ab, bevor du fortfährst.`}</span>
        </p>
      </div>
      <div role="group" aria-labelledby="admin-token-label" className="flex flex-col gap-1.5">
        <p id="admin-token-label" className="font-semibold">{t`Admin-Token`}</p>
        {/* Plain text, not a field: it grows to show the whole token at any width, and one tap selects all of it. */}
        <code
          data-testid="admin-token"
          className="block rounded-r2 border border-line-strong bg-sunken px-3 py-2.5 text-[16px] break-all text-ink select-all"
        >
          {created}
        </code>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button onPress={() => void copyToken(created)} className={SECONDARY_BUTTON}>
          {t`Token kopieren`}
        </Button>
        <span role="status" className="text-small text-ink-2">
          {copy === "done" ? t`Kopiert` : copy === "failed" ? t`Kopieren fehlgeschlagen. Markiere das Token und kopiere es von Hand.` : ""}
        </span>
      </div>
      <p className="text-ink-2">
        <Trans>
          Entferne <code>BAMBUBRIDGE_BOOTSTRAP_ADMIN_KEY</code> aus dem Container; der Schlüssel wirkt nicht mehr, sobald dieses Token existiert.
        </Trans>
      </p>
      <p className="text-small text-ink-2">
        <Trans>
          Token verloren? Auf dem Server legt <code>bambubridge admin create-key</code> ein neues an.
        </Trans>
      </p>
      {error ? <ErrorNote>{error}</ErrorNote> : null}
      <Button onPress={() => void proceed(created)} isDisabled={busy} className={PRIMARY_BUTTON}>
        {t`Weiter zur Oberfläche`}
        <BusyMark show={slow} />
      </Button>
    </AuthScreen>
  );
}
