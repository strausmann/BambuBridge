import { useLingui } from "@lingui/react/macro";
import { Link, Outlet } from "@tanstack/react-router";
import { ChevronRightIcon, DeviceIcon } from "../shell/icons";
import { TEXT_LINK } from "../shell/ui";

/** Focus ring for a plain link (react-aria's data attribute is not set on router links). */
const FOCUS_LINK = "focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link";

/** A page whose content arrives with a later step; the shell and its route exist already. */
function Pending({ title }: { title: string }) {
  const { t } = useLingui();
  return (
    <div className="max-w-2xl">
      <h1 className="text-title font-bold">{title}</h1>
      <p className="mt-2 text-ink-2">{t`Diese Seite ist noch leer. Ihr Inhalt folgt in einer der nächsten Versionen.`}</p>
    </div>
  );
}

export function OverviewPage() {
  const { t } = useLingui();
  return <Pending title={t`Übersicht`} />;
}

export function ProvidersPage() {
  const { t } = useLingui();
  return <Pending title={t`Anbieter`} />;
}

export function ProtocolPage() {
  const { t } = useLingui();
  return <Pending title={t`Protokoll`} />;
}


/** Layout of `/settings/*`; the sections are children of this route. */
export function SettingsLayout() {
  return <Outlet />;
}

/**
 * `/settings`: the list of its sub-pages. On a phone there is no sidebar, so every page below the
 * main destinations is reached from here; the sections themselves arrive with the management pages.
 */
export function SettingsPage() {
  const { t } = useLingui();
  return (
    <div className="max-w-2xl">
      <h1 className="text-title font-bold">{t`Einstellungen`}</h1>
      <nav aria-label={t`Einstellungsseiten`} className="mt-6">
        <ul className="flex flex-col overflow-hidden rounded-r3 border border-line bg-surface">
          <li>
            <Link to="/device" className={`press flex min-h-14 items-center gap-3 px-4 py-2 text-ink hover:bg-sunken ${FOCUS_LINK}`}>
              <DeviceIcon className="shrink-0 text-ink-2" />
              <span className="min-w-0 flex-1">
                <span className="block font-semibold">{t`Dieses Gerät`}</span>
                <span className="block text-small text-ink-2">{t`Verbindung, App-Installation und Versionen`}</span>
              </span>
              <ChevronRightIcon className="shrink-0 text-ink-3" />
            </Link>
          </li>
        </ul>
      </nav>
    </div>
  );
}

export function NotFoundPage() {
  const { t } = useLingui();
  return (
    <div className="max-w-2xl p-4 lg:p-8">
      <h1 className="text-title font-bold">{t`Seite nicht gefunden`}</h1>
      <p className="mt-2 text-ink-2">{t`Diese Adresse gibt es in der BambuBridge nicht.`}</p>
      <p className="mt-4">
        <Link to="/" className={TEXT_LINK}>
          {t`Zur Übersicht`}
        </Link>
      </p>
    </div>
  );
}
