import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";
import { createAppRouter } from "./app/router";

/** German is the source language: without a catalog the messages render as written in the code. */
export function activateGerman(): void {
  i18n.load("de", {});
  i18n.activate("de");
}

export function testQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } });
}

/** Renders a piece of UI with the language and query providers (no router). */
export function renderWithProviders(ui: ReactNode, queryClient = testQueryClient()): RenderResult & { queryClient: QueryClient } {
  activateGerman();
  const result = render(
    <I18nProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </I18nProvider>,
  );
  return { ...result, queryClient };
}

/** Renders the whole app (root layout and routes) at `path` with an in-memory history. */
export function renderApp(path = "/", queryClient = testQueryClient()) {
  activateGerman();
  const history = createMemoryHistory({ initialEntries: [path] });
  const router = createAppRouter({ history });
  const result = render(
    <I18nProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </I18nProvider>,
  );
  return { ...result, router, history, queryClient };
}

type Handler = (init: RequestInit) => Response | Promise<Response>;

export function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), { status: 200, ...init, headers: { "Content-Type": "application/json", ...init.headers } });
}

export function problemResponse(status: number, error_code: string, title: string): Response {
  return new Response(JSON.stringify({ type: "about:blank", title, status, error_code, extensions: {} }), {
    status,
    headers: { "Content-Type": "application/problem+json" },
  });
}

export interface FetchCall {
  method: string;
  path: string;
  headers: Headers;
  body: unknown;
}

/**
 * What the management pages read when a test is about something else (the shell, the session):
 * empty lists, a ready server. A test of a page names its own answers, which win.
 */
function pageDefault(method: string, path: string): Response | undefined {
  if (method !== "GET") return undefined;
  const route = path.split("?")[0];
  if (route === "/readiness") return jsonResponse({ database: "ok", listener: "ok" });
  if (route === "/api/v1/providers" || route === "/api/v1/provider-types" || route === "/api/v1/settings" || route === "/api/v1/admin/api-keys") return jsonResponse([]);
  if (route === "/api/v1/events" || route === "/api/v1/communication") return jsonResponse({ items: [], next_cursor: null });
  return undefined;
}

/**
 * A `fetch` that answers from a table keyed `"METHOD /path"`; an unknown request fails the test
 * loudly instead of hanging (except the reads of the management pages, see `pageDefault`).
 * Returns the calls it saw.
 */
export function stubFetch(routes: Record<string, Handler>): FetchCall[] {
  const calls: FetchCall[] = [];
  globalThis.fetch = ((input: RequestInfo | URL, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const path = String(input);
    calls.push({ method, path, headers: new Headers(init.headers), body: typeof init.body === "string" ? (JSON.parse(init.body) as unknown) : undefined });
    const handler = routes[`${method} ${path}`];
    if (!handler) {
      const fallback = pageDefault(method, path);
      return fallback ? Promise.resolve(fallback) : Promise.reject(new Error(`unexpected request: ${method} ${path}`));
    }
    return Promise.resolve(handler(init));
  }) as typeof fetch;
  return calls;
}

export const SESSION = {
  kind: "session",
  scope: "admin",
  user: "admin",
  identity_provider: null,
  identity_subject: null,
  expires_at: "2099-01-01T00:00:00Z",
  csrf_token: "csrf-1",
} as const;

export const INFO = { name: "BambuBridge", version: "0.2.0", build: "abc1234", bootstrap_open: true } as const;

/** Answers for a signed-in admin: the session and the public info. */
export const SIGNED_IN: Record<string, Handler> = {
  "GET /api/v1/auth/session": () => jsonResponse(SESSION),
  "GET /api/v1/info": () => jsonResponse(INFO),
};

export const DEMO_TYPE = {
  kind: "integration",
  type_name: "demo",
  config_schema: {
    type: "object",
    properties: {
      interval_seconds: { type: "integer", minimum: 1, maximum: 3600, default: 30, title: "Interval (seconds)" },
      label: { type: "string", minLength: 1, maxLength: 100, default: "demo", title: "Label" },
      token: { type: "string", "x-secret": true, minLength: 8, maxLength: 512, title: "Token" },
    },
    required: ["token"],
    additionalProperties: false,
  },
  event_types: [{ name: "integration.demo.tick", schema_version: 1, payload_schema: { type: "object", properties: { sequence: { type: "integer" } } } }],
  actions: [{ name: "emit_now", params_schema: { type: "object", properties: {} } }],
} as const;

export const DEMO_INSTANCE = {
  id: "11111111-1111-4111-8111-111111111111",
  kind: "integration",
  type_name: "demo",
  name: "Workshop demo",
  enabled: true,
  config: { interval_seconds: 30, label: "demo" },
  secrets: { token: { set: true } },
  status: { state: "connected", message: null, since: "2026-11-17T08:00:00Z" },
  created_by: null,
  updated_by: null,
  updated_at: "2026-11-17T08:00:00Z",
} as const;

export const EVENT = {
  id: "22222222-2222-4222-8222-222222222222",
  occurred_at: "2026-11-17T09:00:00Z",
  type: "integration.demo.tick",
  source_instance_id: DEMO_INSTANCE.id,
  schema_version: 1,
  correlation_id: null,
  payload: { label: "demo", sequence: 7 },
  delivery_status: "done",
} as const;
