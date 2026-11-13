import { useEffect, useRef, type ReactNode } from "react";

/** Space between the last line of the page and the notes above it. */
export const NOTICE_GAP_PX = 12;

/**
 * Publishes how much room the notes take as `--notice-h` on the root element (their height plus
 * a gap, `0px` while none is shown). The page adds it to its bottom padding, so its last
 * control can always be scrolled clear of a note instead of ending under it.
 */
function usePublishedHeight(ref: React.RefObject<HTMLDivElement | null>): void {
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const root = document.documentElement;
    const observer = new ResizeObserver(([entry]) => {
      const height = Math.ceil(entry?.contentRect.height ?? 0);
      root.style.setProperty("--notice-h", height > 0 ? `${height + NOTICE_GAP_PX}px` : "0px");
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--notice-h");
    };
  }, [ref]);
}

/**
 * Where page-wide notes appear: above the tab bar on a phone (`aboveTabBar`), in the bottom
 * corner on a wide screen. They stack when there are two, and the page keeps room below its
 * last control for them (`--notice-h`), so they cover no heading and no control.
 */
export function NoticeArea({ aboveTabBar, children }: { aboveTabBar: boolean; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  usePublishedHeight(ref);
  return (
    <div
      ref={ref}
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
