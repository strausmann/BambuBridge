import { useLingui } from "@lingui/react/macro";
import { Link, Outlet } from "@tanstack/react-router";
import { TEXT_LINK } from "../shell/ui";

/** Layout of `/settings/*`; the sections are children of this route. */
export function SettingsLayout() {
  return <Outlet />;
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
