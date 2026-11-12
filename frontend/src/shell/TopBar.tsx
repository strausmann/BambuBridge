import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { Button } from "react-aria-components";
import { useSession } from "../app/session";
import { SignOutIcon } from "./icons";
import { LanguageSwitch } from "./LanguageSwitch";
import { Logo } from "./Logo";
import { ThemeSwitch } from "./ThemeSwitch";
import { ICON_BUTTON } from "./ui";

/** Who is signed in, theme, language and sign-out; below 1024 px also the mark (the sidebar is hidden). */
export function TopBar() {
  const { t } = useLingui();
  const session = useSession();

  return (
    <header className="sticky top-0 z-10 flex h-[calc(4rem+env(safe-area-inset-top))] items-center gap-2 border-b border-line bg-surface pt-[env(safe-area-inset-top)] pr-[max(1rem,env(safe-area-inset-right))] pl-[max(1rem,env(safe-area-inset-left))] lg:pr-8 lg:pl-8">
      <Link to="/" aria-label={t`BambuBridge, zur Übersicht`} className="press flex size-11 items-center justify-center rounded-r1 lg:hidden">
        <Logo variant="mark" className="block h-9" />
      </Link>
      <div className="ml-auto flex min-w-0 items-center gap-1">
        {session.user ? (
          <p className="mr-2 hidden min-w-0 truncate text-small text-ink-2 sm:block" data-testid="signed-in-user">
            {t`Angemeldet als ${session.user}`}
          </p>
        ) : null}
        <ThemeSwitch />
        <LanguageSwitch />
        <Button aria-label={t`Abmelden`} onPress={() => void session.signOut()} className={ICON_BUTTON}>
          <SignOutIcon />
        </Button>
      </div>
    </header>
  );
}
