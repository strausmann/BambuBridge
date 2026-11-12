import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useNavEntries } from "./nav";

/** Phone and tablet navigation (below 1024 px): the same destinations as the sidebar, as tabs. */
export function TabBar() {
  const { t } = useLingui();
  const entries = useNavEntries();

  return (
    <nav
      aria-label={t`Hauptnavigation`}
      data-tabbar=""
      className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-4 border-t border-line bg-surface pr-[env(safe-area-inset-right)] pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] lg:hidden"
    >
      {entries.map((entry) => (
        <Link
          key={entry.to}
          to={entry.to}
          activeOptions={{ exact: entry.exact }}
          className="press relative flex h-16 min-w-0 flex-col items-center justify-center gap-0.5 text-small text-ink-2 data-[status=active]:font-semibold data-[status=active]:text-ink"
        >
          {/* A bar over the active tab says "here" without relying on colour. */}
          <span aria-hidden="true" className="absolute top-0 h-0.5 w-10 rounded-full bg-transparent in-data-[status=active]:bg-primary" />
          {entry.icon}
          <span className="max-w-full truncate px-1">{entry.label}</span>
        </Link>
      ))}
    </nav>
  );
}
