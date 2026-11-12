import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { Button, Input, Label, TextField } from "react-aria-components";
import { ApiError } from "../api/client";
import { AuthScreen, ErrorNote } from "./AuthScreen";
import { FIELD, PRIMARY_BUTTON, SECONDARY_BUTTON, TEXT_LINK } from "./ui";

function useSignInMessage() {
  const { t } = useLingui();
  return (error: unknown, how: "token" | "sso"): string => {
    if (!(error instanceof ApiError)) return t`Etwas ist schiefgegangen.`;
    if (error.status === 0) return t`Der Server ist nicht erreichbar.`;
    if (error.status === 429) return t`Zu viele Versuche. Warte eine Minute und versuche es erneut.`;
    if (error.status === 401 && error.code === "user_disabled") return t`Dieser Benutzer ist deaktiviert.`;
    if (error.status === 401 && how === "sso") {
      return t`Die einmalige Anmeldung hat dich nicht erkannt. Öffne die BambuBridge über deinen Anmeldedienst oder melde dich mit einem Token an.`;
    }
    if (error.status === 401) return t`Dieses Token wurde nicht akzeptiert.`;
    return t`Etwas ist schiefgegangen.`;
  };
}

interface Props {
  onSignIn: (token: string) => Promise<void>;
  onSso: () => Promise<void>;
}

/**
 * Sign-in with an API token, or through the server's identity providers (single sign-on behind
 * a trusted proxy). The token is cleared the moment it is sent and never stored in the browser.
 */
export function SignIn({ onSignIn, onSso }: Props) {
  const { t } = useLingui();
  const messageFor = useSignInMessage();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(how: "token" | "sso", action: () => Promise<void>) {
    setError(null);
    setBusy(true);
    try {
      await action();
    } catch (failure) {
      setError(messageFor(failure, how));
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (token === "" || busy) return;
    const sent = token;
    setToken("");
    void run("token", () => onSignIn(sent));
  }

  return (
    <AuthScreen>
      <div>
        <h1 className="text-title font-bold">{t`Anmelden`}</h1>
        <p className="mt-1 text-ink-2">{t`Melde dich mit einem API-Token an.`}</p>
      </div>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <TextField value={token} onChange={setToken} name="api-token" type="password" autoComplete="off" className="flex flex-col gap-1.5">
          <Label className="font-semibold">{t`API-Token`}</Label>
          <Input className={`${FIELD} font-mono`} spellCheck={false} autoCapitalize="none" autoCorrect="off" enterKeyHint="go" />
        </TextField>
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        <Button type="submit" isDisabled={busy} className={PRIMARY_BUTTON}>
          {t`Anmelden`}
        </Button>
      </form>
      <Button isDisabled={busy} onPress={() => void run("sso", onSso)} className={SECONDARY_BUTTON}>
        {t`Mit einmaliger Anmeldung (SSO) fortfahren`}
      </Button>
      <p className="flex flex-wrap items-center gap-x-1.5 text-ink-2">
        <span>{t`Erster Start?`}</span>
        <Link to="/bootstrap" className={TEXT_LINK}>
          {t`Erstes Admin-Token anlegen`}
        </Link>
      </p>
    </AuthScreen>
  );
}
