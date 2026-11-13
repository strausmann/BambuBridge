import publicPaths from "../../pwa-public-paths.json" with { type: "json" };

/**
 * The paths a browser must be able to load without a sign-in: the service worker, the manifest
 * and the files of the app shell. An auth proxy in front of BambuBridge (Pangolin, an SSO
 * gateway) lets exactly these through; everything else needs a session. The same list decides
 * what the service worker precaches (pwa.config.ts), so the worker never holds a file the proxy
 * would hide behind a sign-in page.
 *
 * An entry is a whole path, or a directory followed by `/*`: one file directly in it.
 */
export const PUBLIC_PATHS: readonly string[] = publicPaths;

export function isPublicPath(path: string, patterns: readonly string[] = PUBLIC_PATHS): boolean {
  return patterns.some((pattern) => {
    if (!pattern.endsWith("/*")) return path === pattern;
    const dir = pattern.slice(0, -1);
    const rest = path.slice(dir.length);
    return path.startsWith(dir) && rest !== "" && !rest.includes("/");
  });
}
