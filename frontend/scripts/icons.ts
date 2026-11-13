/**
 * `pnpm icons`: generate the favicon and app icons from the brand mark (docs/brand/README.md:
 * the PNG sizes are produced at build time, never kept by hand). The generator writes next to
 * its source image, so the mark is first copied to `public/favicon.svg`.
 */
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
mkdirSync(new URL("../public/icons", import.meta.url), { recursive: true });
copyFileSync(new URL("../../docs/brand/logos/drehscheibe-light-mark.svg", import.meta.url), new URL("../public/favicon.svg", import.meta.url));
execFileSync(fileURLToPath(new URL("../node_modules/.bin/pwa-assets-generator", import.meta.url)), ["--config", "pwa-assets.config.ts"], { cwd: root, stdio: "inherit" });
