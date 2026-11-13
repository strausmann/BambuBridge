import type { ReactNode } from "react";

/**
 * Where page-wide notes appear: above the tab bar on a phone (`aboveTabBar`), in the bottom
 * corner on a wide screen. They cover no heading and no control, and stack when there are two.
 */
export function NoticeArea({ aboveTabBar, children }: { aboveTabBar: boolean; children: ReactNode }) {
  return (
    <div
      className={`pointer-events-none fixed inset-x-0 z-30 flex flex-col items-center gap-2 pr-[max(1rem,env(safe-area-inset-right))] pl-[max(1rem,env(safe-area-inset-left))] lg:bottom-6 lg:items-end lg:pr-8 ${
        aboveTabBar ? "bottom-[calc(4rem+env(safe-area-inset-bottom)+0.75rem)]" : "bottom-[max(1rem,env(safe-area-inset-bottom))]"
      }`}
    >
      {children}
    </div>
  );
}

/** One note: a shape beside the words (the state never rests on colour alone), an optional action. */
export function Notice({ tone, icon, children, action }: { tone: "info" | "warn"; icon: ReactNode; children: ReactNode; action?: ReactNode }) {
  return (
    <div
      role="status"
      className={`notice pointer-events-auto flex w-full max-w-md items-center gap-3 rounded-r2 border border-line-strong py-1 pr-1 pl-3 text-ink ${tone === "warn" ? "bg-warn-soft" : "bg-info-soft"}`}
    >
      <span className={`shrink-0 ${tone === "warn" ? "text-warn" : "text-info"}`}>{icon}</span>
      <span className="min-w-0 flex-1 py-2">{children}</span>
      {action}
    </div>
  );
}
