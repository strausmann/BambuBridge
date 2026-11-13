import { useLingui } from "@lingui/react/macro";
import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { TabBar } from "./TabBar";
import { TopBar } from "./TopBar";

/** Sidebar from 1024 px, bottom tab bar below; the top bar carries the session controls. */
export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useLingui();
  return (
    <div className="flex min-h-dvh">
      <a
        href="#content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("content")?.focus();
        }}
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-r2 focus:bg-surface focus:px-4 focus:py-2 focus:font-semibold"
      >
        {t`Zum Inhalt springen`}
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        {/* Bottom padding keeps the last line clear of the tab bar and the home indicator. */}
        <main id="content" tabIndex={-1} className="flex-1 p-4 pb-[calc(6rem+env(safe-area-inset-bottom)+var(--notice-h,0px))] outline-none lg:p-8 lg:pb-[calc(2rem+var(--notice-h,0px))]">
          {children}
        </main>
      </div>
      <TabBar />
    </div>
  );
}
