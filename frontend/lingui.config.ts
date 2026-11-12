import { defineConfig } from "@lingui/cli";
import { formatter } from "@lingui/format-po";

// German is the source language (the messages in the code are German); English is the translation.
export default defineConfig({
  sourceLocale: "de",
  locales: ["de", "en"],
  fallbackLocales: { default: "de" },
  catalogs: [
    {
      path: "<rootDir>/src/i18n/locales/{locale}/messages",
      include: ["<rootDir>/src"],
    },
  ],
  format: formatter({ lineNumbers: false }),
  compileNamespace: "ts",
});
