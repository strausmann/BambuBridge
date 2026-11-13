import { useLingui } from "@lingui/react/macro";
import { useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { OverviewIcon, ProtocolIcon, ProvidersIcon, SettingsIcon } from "./icons";

export type NavPath = "/" | "/providers" | "/protocol" | "/settings";

export interface NavEntry {
  to: NavPath;
  label: string;
  icon: ReactNode;
  /** Only the exact path is "here" (the overview would otherwise match every path). */
  exact: boolean;
  /** Pages outside this path that belong to this destination (reached from it). */
  alsoFor?: readonly string[];
}

/** The main destinations, shared by the sidebar (desktop) and the tab bar (phone). */
export function useNavEntries(): NavEntry[] {
  const { t } = useLingui();
  return [
    { to: "/", label: t`Übersicht`, icon: <OverviewIcon />, exact: true },
    { to: "/providers", label: t`Anbieter`, icon: <ProvidersIcon />, exact: false },
    { to: "/protocol", label: t`Protokoll`, icon: <ProtocolIcon />, exact: false },
    { to: "/settings", label: t`Einstellungen`, icon: <SettingsIcon />, exact: false, alsoFor: ["/device"] },
  ];
}

/**
 * Extra props that mark `entry` as "here" on a page it owns outside its own path (`/device`
 * belongs to the settings): the same `data-status` and `aria-current` the router sets on a path
 * match, so styles and assistive technology treat both alike.
 */
export function useOwnedPageProps(entry: NavEntry): { "data-status"?: "active"; "aria-current"?: "page" } {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  return entry.alsoFor?.includes(pathname) ? { "data-status": "active", "aria-current": "page" } : {};
}
