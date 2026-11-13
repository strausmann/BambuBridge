import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useRef, useState, type FormEvent } from "react";
import { Input, Label, TextField } from "react-aria-components";
import { useDirtyGuard } from "../app/dirtyGuard";
import { ApiError } from "../api/client";
import { AuthScreen, ErrorNote } from "./AuthScreen";
import { BusyButton } from "./Busy";
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
 * a trusted proxy). The token is never stored by this page. A refused token is cleared; after
 * any other failure (no answer, rate limit, server error) it stays, so it need not be typed again.
 */
export function SignIn({ onSignIn, onSso }: Props) {
  const { t } = useLingui();
  const messageFor = useSignInMessage();
  const [token, setToken] = useState("");
  // A typed token is input a new version must not reload away (src/app/updates.ts).
  useDirtyGuard(token !== "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"token" | "sso" | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const ssoButton = useRef<HTMLButtonElement>(null);

  async function run(how: "token" | "sso", action: () => Promise<void>) {
    setError(null);
    setBusy(how);
    // Held before the request: after a sign-in that went through, this screen is gone.
    const input = field.current;
    try {
      await action();
      if (how === "token") {
        // The page is done with the token: drop it from the state and from the field itself.
        setToken("");
        if (input) {
          input.value = "";
          input.removeAttribute("value");
        }
      }
    } catch (failure) {
      if (how === "token" && failure instanceof ApiError && failure.status === 401) setToken("");
      setError(messageFor(failure, how));
      setBusy(null);
      // The pressed button was disabled while busy and has lost the focus. Give it back where
      // the next step is: the field for a token, the same button for single sign-on.
      (how === "token" ? field.current : ssoButton.current)?.focus();
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (token === "" || busy !== null) return;
    void run("token", () => onSignIn(token));
  }

  return (
    <AuthScreen>
      <div>
        <h1 className="text-title font-bold">{t`Anmelden`}</h1>
        <p className="mt-1 text-ink-2">{t`Melde dich mit einem API-Token an.`}</p>
      </div>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <TextField value={token} onChange={setToken} name="api-token" type="password" autoComplete="current-password" className="flex flex-col gap-1.5">
          <Label className="font-semibold">{t`API-Token`}</Label>
          <Input ref={field} className={`${FIELD} font-mono`} spellCheck={false} autoCapitalize="none" autoCorrect="off" enterKeyHint="go" />
        </TextField>
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        <BusyButton type="submit" busy={busy === "token"} isDisabled={busy !== null} className={PRIMARY_BUTTON}>
          {t`Anmelden`}
        </BusyButton>
      </form>
      <BusyButton ref={ssoButton} busy={busy === "sso"} isDisabled={busy !== null} onPress={() => void run("sso", onSso)} className={SECONDARY_BUTTON}>
        {t`Mit einmaliger Anmeldung (SSO) fortfahren`}
      </BusyButton>
      <p className="flex flex-wrap items-center gap-x-1.5 text-ink-2">
        <span>{t`Erster Start?`}</span>
        <Link to="/bootstrap" className={TEXT_LINK}>
          {t`Erstes Admin-Token anlegen`}
        </Link>
      </p>
    </AuthScreen>
  );
}
