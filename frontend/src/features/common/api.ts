import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { ApiError, apiFetch } from "../../api/client";
import type { components } from "../../api/schema.gen";

type Schemas = components["schemas"];

export type ProviderInstance = Schemas["ProviderInstanceView"];
export type ProviderType = Schemas["ProviderTypeView"];
export type EventView = Schemas["EventView"];
export type EventDetailData = Schemas["EventDetail"];
export type EventPage = Schemas["EventPage"];
export type CommunicationSummary = Schemas["CommunicationSummary"];
export type CommunicationDetailData = Schemas["CommunicationDetail"];
export type CommunicationPage = Schemas["CommunicationPage"];
export type SettingView = Schemas["SettingView"];
export type ApiKeyRead = Schemas["ApiKeyRead"];
export type ProbeResult = Schemas["ProbeResultView"];
export type DeliveryStatus = EventView["delivery_status"];

export const PROVIDERS_KEY = ["providers"] as const;
export const PROVIDER_TYPES_KEY = ["provider-types"] as const;
export const SETTINGS_KEY = ["settings"] as const;
export const API_KEYS_KEY = ["api-keys"] as const;

/** How often the lists that show live data ask again. */
export const LIVE_POLL_MS = 5_000;

export function useProviders(): UseQueryResult<ProviderInstance[]> {
  return useQuery({ queryKey: PROVIDERS_KEY, queryFn: () => apiFetch<ProviderInstance[]>("/api/v1/providers"), refetchInterval: LIVE_POLL_MS });
}

export function useProviderTypes(): UseQueryResult<ProviderType[]> {
  return useQuery({ queryKey: PROVIDER_TYPES_KEY, queryFn: () => apiFetch<ProviderType[]>("/api/v1/provider-types"), staleTime: 300_000 });
}

export function useSettings(): UseQueryResult<SettingView[]> {
  return useQuery({ queryKey: SETTINGS_KEY, queryFn: () => apiFetch<SettingView[]>("/api/v1/settings") });
}

export interface ReadinessState {
  /** The server answered 200: the database and the settings listener are both up. */
  ready: boolean;
  database: "ok" | "unavailable" | "unknown";
  listener: "ok" | "unavailable" | "unknown";
}

const isPart = (value: unknown): value is "ok" | "unavailable" => value === "ok" || value === "unavailable";

/**
 * `/readiness` answers 503 with the state of each part in its body; that body is read. A 503
 * without such a body reads as "not ready, parts unknown". Anything else (no network, 401) is an error.
 */
export async function fetchReadiness(): Promise<ReadinessState> {
  try {
    const body = await apiFetch<{ database: "ok" | "unavailable"; listener: "ok" | "unavailable" }>("/readiness");
    return { ready: body.database === "ok" && body.listener === "ok", database: body.database, listener: body.listener };
  } catch (error) {
    if (error instanceof ApiError && error.status === 503) {
      const body = error.body as { database?: unknown; listener?: unknown } | null | undefined;
      if (body && isPart(body.database) && isPart(body.listener)) return { ready: false, database: body.database, listener: body.listener };
      return { ready: false, database: "unknown", listener: "unknown" };
    }
    throw error;
  }
}

export function useReadiness(): UseQueryResult<ReadinessState> {
  return useQuery({ queryKey: ["readiness"], queryFn: fetchReadiness, refetchInterval: LIVE_POLL_MS });
}

/** Reads `key` of a record without walking the prototype chain (the keys come from the server). */
export function field<T>(record: Record<string, T> | undefined, key: string): T | undefined {
  if (record === undefined || !Object.hasOwn(record, key)) return undefined;
  return new Map(Object.entries(record)).get(key);
}

/** A copy of `record` with `key` set, or removed when `value` is `undefined`. */
export function withField<T>(record: Record<string, T>, key: string, value: T | undefined): Record<string, T> {
  const entries = Object.entries(record).filter(([name]) => name !== key);
  if (value !== undefined) entries.push([key, value]);
  return Object.fromEntries(entries);
}
