import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useInfo } from "../app/session";
import { Logo } from "./Logo";
import { useNavEntries, useOwnedPageProps, type NavEntry } from "./nav";

/** Desktop navigation (from 1024 px): logo, the main destinations, server version at the foot. */
export function Sidebar() {
  const { t } = useLingui();
  const info = useInfo();
  const entries = useNavEntries();
  const version = info.data?.version;

  return (
    <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-line bg-surface lg:flex">
      <div className="px-5 pt-5 pb-4">
        <Link to="/" aria-label={t`BambuBridge, zur Übersicht`} className="press inline-flex h-11 items-center rounded-r1">
          <Logo className="block h-8" />
        </Link>
      </div>
      <nav aria-label={t`Hauptnavigation`} className="flex-1 overflow-y-auto px-3 pb-4">
        <ul className="flex flex-col gap-1">
          {entries.map((entry) => (
            <li key={entry.to}>
              <SideLink entry={entry} />
            </li>
          ))}
        </ul>
      </nav>
      <p className="border-t border-line px-6 py-4 text-small text-ink-3">
        {version ? t`Version ${version}` : info.isError ? t`Server nicht erreichbar` : t`Verbinde …`}
      </p>
    </aside>
  );
}

function SideLink({ entry }: { entry: NavEntry }) {
  const owned = useOwnedPageProps(entry);
  return (
    <Link
      to={entry.to}
      activeOptions={{ exact: entry.exact }}
      {...owned}
      className="press relative flex h-11 items-center gap-3 rounded-r2 px-3 text-ink-2 hover:bg-sunken hover:text-ink data-[status=active]:bg-primary-soft data-[status=active]:font-semibold data-[status=active]:text-ink"
    >
      {/* A bar marks the current page without relying on colour alone. */}
      <span aria-hidden="true" className="absolute top-2.5 bottom-2.5 left-0 w-1 rounded-full bg-transparent in-data-[status=active]:bg-primary" />
      {entry.icon}
      <span>{entry.label}</span>
    </Link>
  );
}
