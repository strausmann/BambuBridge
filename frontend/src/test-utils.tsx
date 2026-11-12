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
 * A `fetch` that answers from a table keyed `"METHOD /path"`; an unknown request fails the test
 * loudly instead of hanging. Returns the calls it saw.
 */
export function stubFetch(routes: Record<string, Handler>): FetchCall[] {
  const calls: FetchCall[] = [];
  globalThis.fetch = ((input: RequestInfo | URL, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const path = String(input);
    calls.push({ method, path, headers: new Headers(init.headers), body: typeof init.body === "string" ? (JSON.parse(init.body) as unknown) : undefined });
    const handler = routes[`${method} ${path}`];
    if (!handler) return Promise.reject(new Error(`unexpected request: ${method} ${path}`));
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

export const INFO = { name: "BambuBridge", version: "0.2.0", build: "abc1234" } as const;
