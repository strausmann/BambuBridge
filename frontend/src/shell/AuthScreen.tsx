import type { ReactNode } from "react";
import { LanguageSwitch } from "./LanguageSwitch";
import { Logo } from "./Logo";
import { ThemeSwitch } from "./ThemeSwitch";

/**
 * Frame of the screens before the shell (sign-in, first start): logo, one panel, theme and
 * language. On a short viewport (on-screen keyboard open) the panel sits at the top and the
 * page scrolls, so the focused field and the button below it stay reachable.
 */
export function AuthScreen({ children }: { children: ReactNode }) {
  return (
    <main className="grid min-h-dvh place-items-center px-4 pt-[max(1rem,env(safe-area-inset-top))] pb-[max(1rem,env(safe-area-inset-bottom))] short:place-items-start short:justify-items-center">
      <div className="flex w-full max-w-md min-w-0 flex-col gap-6">
        <Logo className="block h-10" />
        <section className="flex flex-col gap-5 rounded-r3 border border-line bg-surface p-6">{children}</section>
        <div className="flex items-center justify-between">
          <ThemeSwitch />
          <LanguageSwitch />
        </div>
      </div>
    </main>
  );
}

/** An error line: a shape next to the words, so the state does not rest on colour alone. */
export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="flex items-start gap-2 rounded-r2 bg-bad-soft px-3 py-2 text-ink">
      <svg viewBox="0 0 16 16" width="16" height="16" className="mt-0.5 shrink-0 text-bad" aria-hidden="true" data-shape="error">
        <path d="M8 1.5 15 14H1L8 1.5Z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M8 6.5v3.5M8 12v.25" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <span>{children}</span>
    </p>
  );
}
