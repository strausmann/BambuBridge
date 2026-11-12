import { useLingui } from "@lingui/react/macro";
import { createRootRoute, createRoute, createRouter, getRouteApi, Outlet, useLocation, useRouter, type RouterHistory } from "@tanstack/react-router";
import { useEffect } from "react";
import { Button } from "react-aria-components";
import { ApiError, apiFetch } from "../api/client";
import { DevicePage, NotFoundPage, OverviewPage, ProtocolPage, ProvidersPage, SettingsLayout, SettingsPage } from "../pages/placeholders";
import { AppShell } from "../shell/AppShell";
import { BootstrapKeyCreated } from "../shell/BootstrapKeyCreated";
import { SignIn } from "../shell/SignIn";
import { PRIMARY_BUTTON } from "../shell/ui";
import { useSession, type ApiKeyCreated } from "./session";

export const BOOTSTRAP_HEADER = "X-BambuBridge-Bootstrap";

/** Paths shown without a sign-in. */
const PUBLIC_PATHS = ["/sign-in", "/bootstrap"];

/** Paths the server answers itself; the app never sends a visitor there after a sign-in. */
const SERVER_PATHS = ["/api", "/auth", "/docs", "/openapi.json"];

const isOrBelow = (pathname: string, base: string): boolean => pathname === base || pathname.startsWith(`${base}/`);

/**
 * A sign-in return target must stay on this site and inside the app. The value is resolved the
 * way the browser would resolve it (dot segments, percent-encoded dots) and the result is
 * checked and returned, so what was checked is what is used. Rejected: anything that is not a
 * path, any backslash (browsers read it as a slash), control characters (browsers drop them), a
 * result on another origin or starting with `//`, the server's own paths and the public pages.
 */
export function safeRedirect(value: unknown): string | undefined {
  if (typeof value !== "string" || !value.startsWith("/")) return undefined;
  if (value.includes("\\") || /%5c/i.test(value)) return undefined;
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(value)) return undefined;
  let url: URL;
  try {
    url = new URL(value, window.location.origin);
  } catch {
    return undefined;
  }
  if (url.origin !== window.location.origin) return undefined;
  const { pathname } = url;
  if (pathname.startsWith("//") || pathname.includes("\\")) return undefined;
  if (SERVER_PATHS.some((base) => isOrBelow(pathname, base))) return undefined;
  if (PUBLIC_PATHS.some((base) => isOrBelow(pathname, base))) return undefined;
  return `${pathname}${url.search}${url.hash}`;
}

/** Replaces the current history entry (a redirect should not leave a back-button trap). */
function RedirectTo({ href }: { href: string }) {
  const router = useRouter();
  useEffect(() => {
    router.history.replace(href);
  }, [router, href]);
  return null;
}

function Splash() {
  const { t } = useLingui();
  return (
    <div role="status" className="grid min-h-dvh place-items-center text-ink-2">
      {t`Lädt …`}
    </div>
  );
}

function Unreachable({ onRetry }: { onRetry: () => void }) {
  const { t } = useLingui();
  return (
    <main className="grid min-h-dvh place-items-center p-4">
      <div className="flex max-w-sm flex-col items-start gap-4">
        <h1 className="text-title font-bold">{t`Der Server ist nicht erreichbar.`}</h1>
        <p className="text-ink-2">{t`Prüfe die Verbindung und versuche es erneut.`}</p>
        <Button onPress={onRetry} className={PRIMARY_BUTTON}>
          {t`Erneut versuchen`}
        </Button>
      </div>
    </main>
  );
}

/**
 * Decides what the visitor sees: a splash until the server answered, the sign-in (or the
 * first-start screen) while signed out, remembering where they were, and the shell otherwise.
 */
function RootLayout() {
  const session = useSession();
  const location = useLocation();
  const onPublicPage = PUBLIC_PATHS.includes(location.pathname);
  if (session.isPending) return <Splash />;
  if (session.isError) return <Unreachable onRetry={() => void session.refetch()} />;
  if (!session.signedIn) {
    if (onPublicPage) return <Outlet />;
    return <RedirectTo href={`/sign-in?redirect=${encodeURIComponent(location.href)}`} />;
  }
  if (onPublicPage) return <Outlet />;
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

const rootRoute = createRootRoute({ component: RootLayout, notFoundComponent: NotFoundPage });

const signInApi = getRouteApi("/sign-in");

function SignInRoute() {
  const session = useSession();
  const { redirect } = signInApi.useSearch();
  if (session.signedIn) return <RedirectTo href={safeRedirect(redirect) ?? "/"} />;
  return <SignIn onSignIn={session.signIn} onSso={session.signInWithSso} />;
}

/** The first admin token: created with the one-time bootstrap key, never with a session. */
export async function createFirstAdminToken(bootstrapKey: string): Promise<string> {
  const created = await apiFetch<ApiKeyCreated>("/api/v1/admin/api-keys", {
    method: "POST",
    headers: { [BOOTSTRAP_HEADER]: bootstrapKey },
    json: { name: "First admin token", scope: "admin" },
    skipAuthHandler: true,
  });
  // A 2xx without a token must not lead to a screen that shows an empty one.
  const token: unknown = (created as { token?: unknown } | null | undefined)?.token;
  if (typeof token !== "string" || token === "") throw new ApiError(200, "unexpected_content", "The server answered without a token");
  return token;
}

function BootstrapRoute() {
  const session = useSession();
  if (session.signedIn) return <RedirectTo href="/" />;
  return <BootstrapKeyCreated onCreate={createFirstAdminToken} onContinue={session.signIn} />;
}

const page = <P extends string>(path: P, component: () => React.JSX.Element) => createRoute({ getParentRoute: () => rootRoute, path, component });

// Settings is a layout with one child per section; the sections arrive with the management pages.
const settingsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/settings", component: SettingsLayout });
const settingsChild = <P extends string>(path: P, component: () => React.JSX.Element) =>
  createRoute({ getParentRoute: () => settingsRoute, path, component });

const signInRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sign-in",
  component: SignInRoute,
  // The key stays in the result even when rejected: the router merges the result over the raw
  // query string, so leaving it out would let the unchecked value through.
  validateSearch: (search: Record<string, unknown>): { redirect: string | undefined } => ({
    redirect: safeRedirect(search.redirect),
  }),
});

const routeTree = rootRoute.addChildren([
  page("/", OverviewPage),
  page("/providers", ProvidersPage),
  page("/protocol", ProtocolPage),
  settingsRoute.addChildren([settingsChild("/", SettingsPage), settingsChild("/$section", SettingsPage)]),
  page("/device", DevicePage),
  page("/bootstrap", BootstrapRoute),
  signInRoute,
]);

export function createAppRouter(options: { history?: RouterHistory } = {}) {
  return createRouter({ routeTree, history: options.history, defaultPreload: "intent" });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
