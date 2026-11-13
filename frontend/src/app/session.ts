import { useMutation, useQuery, useQueryClient, type QueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { ApiError, apiFetch, AuthRequiredError, setCsrfToken, setOnAuthRequired } from "../api/client";
import type { components } from "../api/schema.gen";

export type InfoData = components["schemas"]["Info"];
export type SessionData = components["schemas"]["SessionInfo"];
export type ApiKeyCreated = components["schemas"]["ApiKeyCreated"];

export const INFO_KEY = ["info"] as const;
export const SESSION_KEY = ["session"] as const;

const SESSION_PATH = "/api/v1/auth/session";

/** The server's sign-in hop; outside `/api` and `/auth` is never answered by the service worker. */
export const CONTINUE_PATH = "/auth/continue";

/** Public name, version and build of the server; available before anyone is signed in. */
export function useInfo(): UseQueryResult<InfoData> {
  return useQuery({
    queryKey: INFO_KEY,
    queryFn: () => apiFetch<InfoData>("/api/v1/info"),
    staleTime: 60_000,
  });
}

export interface Session {
  /** True until the first answer of the server is in. */
  isPending: boolean;
  /** The sign-in state could not be read at all (server down), as opposed to "signed out". */
  isError: boolean;
  signedIn: boolean;
  scope: SessionData["scope"] | null;
  /** Display name of the signed-in user. */
  user: string | null;
  /** Subject the identity provider reported; null for a token sign-in. */
  identitySubject: string | null;
  refetch: () => Promise<unknown>;
  /** Sign in with an API token. */
  signIn: (token: string) => Promise<void>;
  /** Ask the server's identity providers (trusted single sign-on headers). */
  signInWithSso: () => Promise<void>;
  /**
   * Ends the session on the server, then here. Rejects when the server did not confirm it (no
   * answer, 5xx, a refusal): the session is then still open and the shell stays as it is.
   */
  signOut: () => Promise<void>;
}

const isUserData = (key: readonly unknown[]): boolean => key[0] !== INFO_KEY[0] && key[0] !== SESSION_KEY[0];

/** Drop everything the previous user could see; keep what is public. */
function resetUserData(queryClient: QueryClient): void {
  queryClient.removeQueries({ predicate: (query) => isUserData(query.queryKey) });
}

/**
 * Counts the changes of the sign-in state made here (signed in, signed out, session ended). A
 * session read that started before a change describes a state that no longer exists; it
 * compares the count when its answer arrives and then applies nothing.
 */
const authChanges = new WeakMap<QueryClient, number>();
const authChangesOf = (queryClient: QueryClient): number => authChanges.get(queryClient) ?? 0;

/** Marks a change of the sign-in state: session reads still under way are outdated from here on. */
function markAuthChange(queryClient: QueryClient): void {
  authChanges.set(queryClient, authChangesOf(queryClient) + 1);
}

function endSession(queryClient: QueryClient): void {
  markAuthChange(queryClient);
  setCsrfToken(null);
  resetUserData(queryClient);
  queryClient.setQueryData(SESSION_KEY, null);
}

/** Another person (or another scope) behind the same cookie must not inherit the cached data. */
function sameIdentity(a: SessionData, b: SessionData): boolean {
  return a.user === b.user && a.scope === b.scope && a.identity_provider === b.identity_provider && a.identity_subject === b.identity_subject;
}

/** A new sign-in state replaces the stored one; a changed identity drops the previous user's data first. */
function storeSession(queryClient: QueryClient, next: SessionData): void {
  markAuthChange(queryClient);
  const previous = queryClient.getQueryData<SessionData | null>(SESSION_KEY);
  if (previous && !sameIdentity(previous, next)) resetUserData(queryClient);
  // Set before the hook's effect runs: the next request may be sent in the same tick.
  setCsrfToken(next.csrf_token ?? null);
  queryClient.setQueryData(SESSION_KEY, next);
}

/** The current sign-in, or null when there is none (the server answers 401 or sends to a login page). */
async function fetchSession(queryClient: QueryClient): Promise<SessionData | null> {
  const startedAt = authChangesOf(queryClient);
  // The sign-in state changed while this read was under way: its answer is about the past.
  // It then touches nothing (CSRF token, cached data) and hands back what is stored now.
  const outdated = () => authChangesOf(queryClient) !== startedAt;
  const stored = () => queryClient.getQueryData<SessionData | null>(SESSION_KEY) ?? null;
  try {
    const next = await apiFetch<SessionData>(SESSION_PATH, { skipAuthHandler: true });
    if (outdated()) return stored();
    const previous = queryClient.getQueryData<SessionData | null>(SESSION_KEY);
    if (previous && !sameIdentity(previous, next)) resetUserData(queryClient);
    return next;
  } catch (error) {
    if (!(error instanceof AuthRequiredError)) throw error;
    if (outdated()) return stored();
    // An open session that is gone now ended under the user's hands (expired, revoked, the
    // proxy's own sign-in ran out): the same way out as any other request that finds it gone.
    if (stored() !== null) sessionEndedHandler?.();
    setCsrfToken(null);
    resetUserData(queryClient);
    return null;
  }
}

export function useSession(): Session {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: SESSION_KEY,
    queryFn: () => fetchSession(queryClient),
    staleTime: 30_000,
  });
  const data = query.data ?? null;
  const csrfToken = data?.csrf_token ?? null;

  useEffect(() => {
    setCsrfToken(csrfToken);
  }, [csrfToken]);

  const open = useMutation({
    // The sign-in answer already carries the session (user, scope, CSRF token).
    mutationFn: (token: string | null) =>
      apiFetch<SessionData>(SESSION_PATH, { method: "POST", skipAuthHandler: true, ...(token === null ? {} : { json: { token } }) }),
    // The variables are the token: nothing keeps the mutation once it settled (see `openSession`).
    gcTime: 0,
    onSuccess: (next) => {
      resetUserData(queryClient);
      storeSession(queryClient, next);
    },
  });

  const close = useMutation({
    mutationFn: () => apiFetch<void>(SESSION_PATH, { method: "DELETE", skipAuthHandler: true }),
    // Confirmed by the server (204), or already gone there (401, login redirect): over here too.
    onSuccess: () => endSession(queryClient),
    // Anything else (no answer, 5xx, a refused request) leaves the session open on the server.
    // Ending it here alone would show "signed out" above a cookie that still works.
    onError: (error) => {
      if (error instanceof AuthRequiredError) endSession(queryClient);
      // The server answered and refused (for instance a CSRF token that went stale): read the
      // session again, so a second attempt carries the current token. No answer, no question.
      else if (error instanceof ApiError && error.status !== 0) void queryClient.invalidateQueries({ queryKey: SESSION_KEY });
    },
  });

  const { mutateAsync: openAsync, reset: resetOpen } = open;
  const { mutateAsync: closeAsync } = close;
  // `reset` detaches this hook from the settled mutation, so `gcTime: 0` removes it, and with it
  // the token, from the mutation cache; an observed mutation is never collected.
  const openSession = useCallback((token: string | null) => openAsync(token).then(() => undefined).finally(resetOpen), [openAsync, resetOpen]);
  const signIn = useCallback((token: string) => openSession(token), [openSession]);
  const signInWithSso = useCallback(() => openSession(null), [openSession]);
  const signOut = useCallback(
    () =>
      closeAsync().catch((error: unknown) => {
        if (!(error instanceof AuthRequiredError)) throw error;
      }),
    [closeAsync],
  );

  return {
    isPending: query.isPending,
    isError: query.isError && query.data === undefined,
    signedIn: data !== null,
    scope: data?.scope ?? null,
    user: data?.user ?? null,
    identitySubject: data?.identity_subject ?? null,
    refetch: query.refetch,
    signIn,
    signInWithSso,
    signOut,
  };
}

let sessionEndedHandler: (() => void) | null = null;

/**
 * True from the moment the page leaves for the sign-in hop until it is gone. If the browser does
 * not leave after all (the navigation was cancelled, or the network is down) or comes back from
 * the back-forward cache, the latch falls back: on `pageshow`, or after `LEAVING_TIMEOUT_MS`.
 * Otherwise the splash would stay until a manual reload.
 */
let leaving = false;
export const LEAVING_TIMEOUT_MS = 10_000;
const leavingListeners = new Set<() => void>();
function setLeaving(value: boolean): void {
  leaving = value;
  leavingListeners.forEach((listener) => listener());
}

export function useLeaving(): boolean {
  return useSyncExternalStore(
    (listener) => {
      leavingListeners.add(listener);
      return () => void leavingListeners.delete(listener);
    },
    () => leaving,
  );
}

/** Where the sign-in hop sends the browser back to: the page it is on now. */
export function continueUrl(): string {
  return `${CONTINUE_PATH}?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
}

/**
 * Any request that finds the sign-in gone ends the session in the shell: the cached data of the
 * previous user is dropped, and the browser goes to `/auth/continue` with a full page load. An
 * SSO proxy in front signs in again on that way and the server opens a new session; without one
 * the server sends the browser on to the sign-in page, remembering where it was. Never `/`: the
 * service worker would answer that from its cache with the same empty shell.
 */
export function installAuthGuard(
  queryClient: QueryClient,
  navigate: (url: string) => void = (url) => window.location.assign(url),
  { leavingTimeoutMs = LEAVING_TIMEOUT_MS }: { leavingTimeoutMs?: number } = {},
): () => void {
  let timer: number | undefined;
  const stayed = () => {
    window.clearTimeout(timer);
    timer = undefined;
    if (leaving) setLeaving(false);
  };
  const ended = () => {
    if (leaving) return;
    const target = continueUrl();
    setLeaving(true);
    timer = window.setTimeout(stayed, leavingTimeoutMs);
    endSession(queryClient);
    navigate(target);
  };
  window.addEventListener("pageshow", stayed);
  setOnAuthRequired(ended);
  sessionEndedHandler = ended;
  return () => {
    window.removeEventListener("pageshow", stayed);
    window.clearTimeout(timer);
    setOnAuthRequired(null);
    sessionEndedHandler = null;
    setLeaving(false);
  };
}
