// @vitest-environment node
import { resolve } from "node:path";
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const eslint = new ESLint({ cwd: resolve(__dirname, "..") });

async function restrictedImports(filePath: string, code: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath: resolve(__dirname, "..", filePath) });
  return result!.messages.filter((m) => m.ruleId === "no-restricted-imports").map((m) => m.message);
}

const OVERLAY_PARTS = ["Modal", "ModalOverlay", "Dialog", "ComboBox", "Popover", "SearchField"];

// The first lint loads ESLint, its plugins and the whole configuration: seconds, not milliseconds.
describe("overlays only through src/shell/overlays", { timeout: 60_000 }, () => {
  it.each(OVERLAY_PARTS)("importing %s from react-aria-components elsewhere is a lint error", async (name) => {
    const code = `import { ${name} } from "react-aria-components";\nexport const X = ${name};\n`;
    const messages = await restrictedImports("src/features/example/Example.tsx", code);
    expect(messages).toHaveLength(1);
    expect(messages[0]).toContain("src/shell/overlays");
  });

  it("inside src/shell/overlays the same import is allowed", async () => {
    const code = `import { Modal, ModalOverlay, Dialog, ComboBox, Popover, SearchField } from "react-aria-components";\nexport const X = [Modal, ModalOverlay, Dialog, ComboBox, Popover, SearchField];\n`;
    expect(await restrictedImports("src/shell/overlays/Example.tsx", code)).toEqual([]);
  });

  it("other parts of react-aria-components stay free to use", async () => {
    const code = `import { Button, Input } from "react-aria-components";\nexport const X = [Button, Input];\n`;
    expect(await restrictedImports("src/features/example/Example.tsx", code)).toEqual([]);
  });
});
