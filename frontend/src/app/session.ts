import { useMutation, useQuery, useQueryClient, type QueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";
import { apiFetch, AuthRequiredError, setCsrfToken, setOnAuthRequired } from "../api/client";
import type { components } from "../api/schema.gen";

export type InfoData = components["schemas"]["Info"];
export type SessionData = components["schemas"]["SessionInfo"];
export type ApiKeyCreated = components["schemas"]["ApiKeyCreated"];

export const INFO_KEY = ["info"] as const;
export const SESSION_KEY = ["session"] as const;

const SESSION_PATH = "/api/v1/auth/session";

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

function endSession(queryClient: QueryClient): void {
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
  const previous = queryClient.getQueryData<SessionData | null>(SESSION_KEY);
  if (previous && !sameIdentity(previous, next)) resetUserData(queryClient);
  // Set before the hook's effect runs: the next request may be sent in the same tick.
  setCsrfToken(next.csrf_token ?? null);
  queryClient.setQueryData(SESSION_KEY, next);
}

/** The current sign-in, or null when there is none (the server answers 401 or sends to a login page). */
async function fetchSession(queryClient: QueryClient): Promise<SessionData | null> {
  try {
    const next = await apiFetch<SessionData>(SESSION_PATH, { skipAuthHandler: true });
    const previous = queryClient.getQueryData<SessionData | null>(SESSION_KEY);
    if (previous && !sameIdentity(previous, next)) resetUserData(queryClient);
    return next;
  } catch (error) {
    if (!(error instanceof AuthRequiredError)) throw error;
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

/**
 * Any request that finds the sign-in gone ends the session in the shell: the cached data of the
 * previous user is dropped and the root layout shows the sign-in, remembering where the user was.
 */
export function installAuthGuard(queryClient: QueryClient): () => void {
  setOnAuthRequired(() => endSession(queryClient));
  return () => setOnAuthRequired(null);
}
