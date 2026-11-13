import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import security from "eslint-plugin-security";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "dist-next", "coverage", "playwright-report", "test-results", "src/api/schema.gen.ts", "src/i18n/locales/**/messages.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  jsxA11y.flatConfigs.recommended,
  reactHooks.configs.flat.recommended,
  security.configs.recommended,
  {
    // Playwright fixtures call their `use` callback; that is not a React hook.
    files: ["e2e/**", "harness/**"],
    rules: { "react-hooks/rules-of-hooks": "off" },
  },
  {
    // Tests and build scripts read fixed files of this repository, index fixed tables, match
    // this build's own output and start fixed tools; none of it sees input from a user.
    files: ["**/*.test.{ts,tsx}", "src/test-utils.tsx", "e2e/**", "harness/**", "scripts/**", "*.config.ts"],
    rules: {
      "security/detect-non-literal-fs-filename": "off",
      "security/detect-object-injection": "off",
      "security/detect-non-literal-regexp": "off",
      "security/detect-unsafe-regex": "off",
      "security/detect-child-process": "off",
    },
  },
  {
    // Dialogs, sheets, comboboxes and search fields carry the on-screen keyboard and back-button
    // handling of src/shell/overlays (visual viewport, inner scrolling, history entry). Built
    // straight from react-aria they would lose it, so the raw parts stay inside that directory.
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/shell/overlays/**"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "react-aria-components",
              importNames: ["Modal", "ModalOverlay", "Dialog", "ComboBox", "Popover", "SearchField"],
              message: "Use AppDialog, AppSheet, AppComboBox or AppSearchField from src/shell/overlays.",
            },
          ],
        },
      ],
    },
  },
  {
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: {
      "@typescript-eslint/consistent-type-imports": "error",
    },
  },
);
