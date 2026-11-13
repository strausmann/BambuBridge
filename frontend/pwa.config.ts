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
 * `/api/`, `/auth/` (the sign-in hop of an SSO proxy must always reach the network), the API
 * reference and the OpenAPI document. A cached answer behind a sign-in is worse than none.
 */
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
    navigateFallbackDenylist: [/^\/api\//, /^\/docs(\/|$)/, /^\/openapi\.json$/, /^\/auth\//, /^\/licenses\//, /^\/(healthz|readiness)$/],
    runtimeCaching: [],
    cleanupOutdatedCaches: true,
    clientsClaim: true,
    skipWaiting: false,
  },
};
