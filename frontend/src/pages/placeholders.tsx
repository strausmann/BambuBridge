import { useLingui } from "@lingui/react/macro";
import { Link, Outlet } from "@tanstack/react-router";
import { TEXT_LINK } from "../shell/ui";

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

export function DevicePage() {
  const { t } = useLingui();
  return <Pending title={t`Dieses Gerät`} />;
}

/** Layout of `/settings/*`; the sections are children of this route. */
export function SettingsLayout() {
  return <Outlet />;
}

export function SettingsPage() {
  const { t } = useLingui();
  return <Pending title={t`Einstellungen`} />;
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
