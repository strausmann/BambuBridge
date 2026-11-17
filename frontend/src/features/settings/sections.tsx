import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { ChevronRightIcon, DeviceIcon, SettingsIcon } from "../../shell/icons";
import { TEXT_LINK } from "../../shell/ui";
import { Card, PageTitle } from "../common/ui";
import { AccessPage } from "./AccessPage";
import { SettingsForm } from "./SettingsForm";
import { SystemPage } from "./SystemPage";

export const SETTINGS_SECTIONS = ["general", "access", "sso", "retention", "system"] as const;
export type SettingsSection = (typeof SETTINGS_SECTIONS)[number];

export function useSectionTitles(): (section: SettingsSection) => { title: string; description: string } {
  const { t } = useLingui();
  const titles = {
    general: { title: t`Allgemein`, description: t`Entdoppelung von Ereignissen` },
    access: { title: t`Zugang`, description: t`API-Tokens und Anmeldung` },
    sso: { title: t`Einmalige Anmeldung (SSO)`, description: t`Kopfzeilen des vorgeschalteten Anmeldedienstes` },
    retention: { title: t`Aufbewahrung`, description: t`Wie lange Ereignisse und Kommunikation bleiben` },
    system: { title: t`System`, description: t`Version, Zustand und Schnittstelle` },
  } as const;
  return (section) => new Map(Object.entries(titles)).get(section) ?? titles.general;
}

const LINK = "press flex min-h-14 items-center gap-3 px-4 py-2 text-ink hover:bg-sunken focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link";

/** `/settings`: every page below the main destinations, so a phone without a sidebar reaches them all. */
export function SettingsIndex() {
  const { t } = useLingui();
  const titles = useSectionTitles();
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <PageTitle>{t`Einstellungen`}</PageTitle>
      <nav aria-label={t`Einstellungsseiten`}>
        <ul className="flex flex-col overflow-hidden rounded-r3 border border-line bg-surface">
          {SETTINGS_SECTIONS.map((section) => (
            <li key={section} className="border-b border-line last:border-b-0">
              <Link to="/settings/$section" params={{ section }} className={LINK}>
                <SettingsIcon className="shrink-0 text-ink-2" />
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold">{titles(section).title}</span>
                  <span className="block text-small text-ink-2">{titles(section).description}</span>
                </span>
                <ChevronRightIcon className="shrink-0 text-ink-3" />
              </Link>
            </li>
          ))}
          <li>
            <Link to="/device" className={LINK}>
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

function Frame({ section, children }: { section: SettingsSection; children: ReactNode }) {
  const { t } = useLingui();
  const titles = useSectionTitles();
  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <Link to="/settings" className={TEXT_LINK}>
        {t`Zurück zu den Einstellungen`}
      </Link>
      <PageTitle>{titles(section).title}</PageTitle>
      {children}
    </div>
  );
}

export function GeneralPage() {
  const { t } = useLingui();
  return (
    <Frame section="general">
      <Card title={t`Ereignisse`} id="general-title">
        <SettingsForm sections={["events"]} />
      </Card>
    </Frame>
  );
}

export function RetentionPage() {
  const { t } = useLingui();
  return (
    <Frame section="retention">
      <Card title={t`Aufbewahrung`} id="retention-title">
        <p className="mb-4 text-ink-2">{t`Ältere Einträge werden gelöscht.`}</p>
        <SettingsForm sections={["retention"]} />
      </Card>
    </Frame>
  );
}

export function SsoPage() {
  const { t } = useLingui();
  return (
    <Frame section="sso">
      <Card title={t`Vorgeschalteter Anmeldedienst`} id="sso-title">
        <SettingsForm sections={["sso"]} />
      </Card>
    </Frame>
  );
}

export function AccessSection() {
  return (
    <Frame section="access">
      <AccessPage />
    </Frame>
  );
}

export function SystemSection() {
  return (
    <Frame section="system">
      <SystemPage />
    </Frame>
  );
}

/** The page of `/settings/$section`; an unknown section is said so, with the way back. */
export function SettingsSectionPage({ section }: { section: string | undefined }) {
  const { t } = useLingui();
  switch (section) {
    case "general":
      return <GeneralPage />;
    case "access":
      return <AccessSection />;
    case "sso":
      return <SsoPage />;
    case "retention":
      return <RetentionPage />;
    case "system":
      return <SystemSection />;
    default:
      return (
        <div className="flex max-w-2xl flex-col gap-3">
          <PageTitle>{t`Einstellung nicht gefunden`}</PageTitle>
          <Link to="/settings" className={TEXT_LINK}>
            {t`Zurück zu den Einstellungen`}
          </Link>
        </div>
      );
  }
}
