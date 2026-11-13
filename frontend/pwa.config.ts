import type { VitePWAOptions } from "vite-plugin-pwa";
import publicPaths from "./pwa-public-paths.json" with { type: "json" };

/**
 * Precache globs from the public path list (pwa-public-paths.json): the worker holds only files
 * an auth proxy serves without a sign-in. `/sw.js` is the worker itself and never precached.
 */
export const precacheGlobs: string[] = publicPaths.filter((path) => path !== "/sw.js").map((path) => path.slice(1));

/**
 * The installable app: a service worker that precaches the app shell (HTML, scripts, styles,
 * fonts, icons) so the installed app opens at once and survives a dropped connection.
 *
 * It never touches the API or the sign-in: no runtime caching, and the navigation fallback skips
 * every path the server owns (`SERVER_PATHS`: the API, `/auth/` — the sign-in hop of an SSO
 * proxy must always reach the network —, the API reference, the OpenAPI document, the licences
 * and the probes) in every spelling the server accepts for it. A cached answer behind a sign-in
 * is worse than none.
 *
 * The precache follows redirects and stores what it gets (Workbox's default; `generateSW` takes
 * no precache plugins, a check of the content type would need our own worker source). It relies
 * on the public path rule: an auth proxy lets exactly `pwa-public-paths.json` through without a
 * sign-in, so these requests never meet a login page (see the deployment docs of Task 19).
 */
/**
 * One character of a server-owned path in any spelling the server decodes to it: the letter
 * in either case or its percent-encoding (`a`, `A`, `%61`, `%41`). Workbox tests the denylist
 * against `pathname + search` as the browser keeps them, still percent-encoded and in the case
 * typed, while the server decodes the path. A literal `/^\/api\//` would let `/%61pi/x` through
 * to the cached shell.
 */
function spelled(char: string): string {
  if (!/[a-z]/i.test(char)) return char === "." ? "(?:\\.|%2e)" : char;
  const lower = char.toLowerCase();
  const upper = char.toUpperCase();
  const hex = (c: string) => `%${c.charCodeAt(0).toString(16)}`;
  return `(?:${lower}|${upper}|${hex(lower)}|${hex(upper)})`;
}

/** The end of a server-owned path segment: a slash (also encoded), the query, or the end. */
const SEGMENT_END = "(?:\\/|%2f|\\?|$)";

/** `/<name>` and everything below or after it, in any spelling the server takes for it. */
export function serverPath(name: string): RegExp {
  return new RegExp(`^\\/${[...name].map(spelled).join("")}${SEGMENT_END}`, "i");
}

/** Paths the server owns: the API, the sign-in hop, the docs and probes. Never the shell. */
export const SERVER_PATHS = ["api", "auth", "docs", "openapi.json", "licenses", "healthz", "readiness"] as const;

export const pwaOptions: Partial<VitePWAOptions> = {
  // The manifest is a plain file in public/ and linked from index.html.
  manifest: false,
  // A new version waits until it is applied (src/app/updates.ts): forcing it on an open tab
  // would leave that tab without the old hashed files it still loads lazily.
  registerType: "prompt",
  injectRegister: false,
  workbox: {
    globPatterns: precacheGlobs,
    // The workbox runtime goes into sw.js itself: no second worker file at the root.
    inlineWorkboxRuntime: true,
    navigateFallback: "/index.html",
    navigateFallbackDenylist: SERVER_PATHS.map(serverPath),
    runtimeCaching: [],
    cleanupOutdatedCaches: true,
    clientsClaim: true,
    skipWaiting: false,
  },
};
