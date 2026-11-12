import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useEffect, useId, useRef, useState } from "react";
import { Button } from "react-aria-components";
import { useSession } from "../app/session";
import { ErrorNote } from "./AuthScreen";
import { CloseIcon, SignOutIcon } from "./icons";
import { LanguageSwitch } from "./LanguageSwitch";
import { Logo } from "./Logo";
import { ThemeSwitch } from "./ThemeSwitch";
import { FOCUS, ICON_BUTTON } from "./ui";

/** Who is signed in, theme, language and sign-out; below 1024 px also the mark (the sidebar is hidden). */
export function TopBar() {
  const { t } = useLingui();
  const session = useSession();
  const userId = useId();
  const [signOutFailed, setSignOutFailed] = useState(false);
  const signOutButton = useRef<HTMLButtonElement>(null);

  function signOut() {
    setSignOutFailed(false);
    // A sign-out the server did not confirm leaves the session open: stay here and say so.
    session.signOut().catch(() => setSignOutFailed(true));
  }

  /** Closing the note returns the focus to the control it is about, for another try. */
  function dismiss() {
    setSignOutFailed(false);
    signOutButton.current?.focus();
  }

  useEffect(() => {
    if (!signOutFailed) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSignOutFailed(false);
      signOutButton.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [signOutFailed]);

  return (
    <header className="sticky top-0 z-10 flex h-[calc(4rem+env(safe-area-inset-top))] items-center gap-2 border-b border-line bg-surface pt-[env(safe-area-inset-top)] pr-[max(1rem,env(safe-area-inset-right))] pl-[max(1rem,env(safe-area-inset-left))] lg:pr-8 lg:pl-8">
      <Link to="/" aria-label={t`BambuBridge, zur Übersicht`} className="press flex size-11 items-center justify-center rounded-r1 lg:hidden">
        <Logo variant="mark" className="block h-9" />
      </Link>
      <div className="ml-auto flex min-w-0 items-center gap-1">
        {session.user ? (
          // Below 640 px there is no room for the line; it still describes the sign-out button.
          <p id={userId} className="sr-only text-small text-ink-2 sm:not-sr-only sm:mr-2 sm:block sm:min-w-0 sm:truncate" data-testid="signed-in-user">
            {t`Angemeldet als ${session.user}`}
          </p>
        ) : null}
        <ThemeSwitch />
        <LanguageSwitch />
        <Button ref={signOutButton} aria-label={t`Abmelden`} aria-describedby={session.user ? userId : undefined} onPress={signOut} className={ICON_BUTTON}>
          <SignOutIcon />
        </Button>
      </div>
      {signOutFailed ? (
        // Above the tab bar on a phone, in the corner on a wide screen: it covers no heading and no control.
        <div className="fixed inset-x-0 bottom-[calc(4rem+env(safe-area-inset-bottom)+0.75rem)] z-30 flex justify-center pr-[max(1rem,env(safe-area-inset-right))] pl-[max(1rem,env(safe-area-inset-left))] lg:bottom-6 lg:justify-end lg:pr-8">
          <div className="flex max-w-md items-start rounded-r2 border border-line-strong bg-bad-soft">
            <ErrorNote>{t`Abmelden fehlgeschlagen, die Sitzung ist noch offen`}</ErrorNote>
            <Button
              aria-label={t`Meldung schließen`}
              onPress={dismiss}
              className={`press flex size-11 shrink-0 items-center justify-center rounded-r2 text-ink hover:bg-surface ${FOCUS}`}
            >
              <CloseIcon />
            </Button>
          </div>
        </div>
      ) : null}
    </header>
  );
}
