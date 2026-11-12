/**
 * `pnpm gen:api`: export the backend's OpenAPI document to `openapi.json` and generate
 * `src/api/schema.gen.ts` from it. Both files are committed; `src/api/schema.test.ts` fails
 * when either is out of date. Needs the backend environment (`uv sync` in `backend/`);
 * `BB_OPENAPI_EXPORT` overrides the export command (run in `backend/`).
 */
import { execSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { renderApiTypes } from "./api-types.ts";

export const EXPORT_COMMAND = process.env.BB_OPENAPI_EXPORT ?? "uv run --frozen python scripts/export_openapi.py";

/** The backend's current OpenAPI document as the text `openapi.json` must hold. */
export function exportOpenApi(): string {
  // Paths from `import.meta.dirname`: this module also runs inside the test runner, where a
  // `new URL(..., import.meta.url)` is rewritten into an asset address.
  return execSync(EXPORT_COMMAND, { cwd: resolve(import.meta.dirname, "..", "..", "backend"), encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const document = exportOpenApi();
  writeFileSync(resolve(import.meta.dirname, "..", "openapi.json"), document);
  writeFileSync(resolve(import.meta.dirname, "..", "src", "api", "schema.gen.ts"), await renderApiTypes(JSON.parse(document)));
  console.log("openapi.json and src/api/schema.gen.ts written");
}
