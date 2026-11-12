import { useLingui } from "@lingui/react/macro";
import type { ReactNode } from "react";
import { OverviewIcon, ProtocolIcon, ProvidersIcon, SettingsIcon } from "./icons";

export type NavPath = "/" | "/providers" | "/protocol" | "/settings";

export interface NavEntry {
  to: NavPath;
  label: string;
  icon: ReactNode;
  /** Only the exact path is "here" (the overview would otherwise match every path). */
  exact: boolean;
}

/** The main destinations, shared by the sidebar (desktop) and the tab bar (phone). */
export function useNavEntries(): NavEntry[] {
  const { t } = useLingui();
  return [
    { to: "/", label: t`Übersicht`, icon: <OverviewIcon />, exact: true },
    { to: "/providers", label: t`Anbieter`, icon: <ProvidersIcon />, exact: false },
    { to: "/protocol", label: t`Protokoll`, icon: <ProtocolIcon />, exact: false },
    { to: "/settings", label: t`Einstellungen`, icon: <SettingsIcon />, exact: false },
  ];
}
