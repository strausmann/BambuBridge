import { readFileSync } from "node:fs";
import { lingui } from "@lingui/vite-plugin";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vitest/config";
import { pwaOptions } from "./pwa.config.ts";

// Licence texts that must travel with the files they cover (OFL-1.1 for the fonts). They are
// copied into `dist/licenses/` and so into the image.
const NOTICES: { from: string; to: string }[] = [
  { from: "node_modules/@fontsource-variable/inter/LICENSE", to: "licenses/inter-OFL-1.1.txt" },
  { from: "node_modules/@fontsource-variable/space-grotesk/LICENSE", to: "licenses/space-grotesk-OFL-1.1.txt" },
  { from: "node_modules/@fontsource-variable/jetbrains-mono/LICENSE", to: "licenses/jetbrains-mono-OFL-1.1.txt" },
];

function licenseNotices(): Plugin {
  return {
    name: "license-notices",
    generateBundle() {
      for (const { from, to } of NOTICES) {
        this.emitFile({ type: "asset", fileName: to, source: readFileSync(new URL(from, import.meta.url), "utf8") });
      }
    },
  };
}

// Same value as the backend's `X-BambuBridge-Version` header (`<VERSION>+<BUILD_ID>`); the image
// build passes both variables to the frontend and the backend stage.
const appVersion = `${process.env.BAMBUBRIDGE_BUILD_VERSION ?? "0.0.0-dev"}+${process.env.BAMBUBRIDGE_BUILD_ID ?? "dev"}`;

// The backend serves `dist/` (same origin), so the dev server proxies the API and the sign-in redirect.
export default defineConfig({
  plugins: [react(), lingui({ macroTransform: true }), tailwindcss(), licenseNotices(), VitePWA(pwaOptions)],
  define: { __APP_VERSION__: JSON.stringify(appVersion) },
  server: {
    // The logo files are read from docs/brand, one level above this project.
    fs: { allow: [".."] },
    proxy: {
      "/api": "http://localhost:8000",
      "/auth": "http://localhost:8000",
    },
  },
  // Assets are never inlined as data: URIs: the logos and fonts stay files of this origin.
  build: { outDir: "dist", sourcemap: false, assetsInlineLimit: 0 },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/api/schema.gen.ts", "src/main.tsx", "src/vite-env.d.ts", "src/test-setup.ts", "src/i18n/locales/**", "src/i18n/po.d.ts", "src/test-utils.tsx"],
      thresholds: { lines: 70, functions: 70, branches: 70, statements: 70 },
    },
  },
});
