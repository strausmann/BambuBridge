import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { renderApiTypes } from "../../scripts/api-types";
import { exportOpenApi } from "../../scripts/gen-api";

const root = resolve(__dirname, "..", "..");
const committedDocument = readFileSync(resolve(root, "openapi.json"), "utf8");
const committedTypes = readFileSync(resolve(__dirname, "schema.gen.ts"), "utf8");

// CI sets REQUIRE_API_EXPORT=1 (the backend environment is installed there), so a missing `uv`
// fails instead of skipping. Locally the export runs whenever `uv` is on the PATH.
const required = process.env.REQUIRE_API_EXPORT === "1";
const hasUv = spawnSync("uv", ["--version"]).status === 0;

describe("API types are up to date (`pnpm gen:api` produces no diff)", () => {
  it("schema.gen.ts is what openapi-typescript generates from openapi.json", async () => {
    expect(await renderApiTypes(JSON.parse(committedDocument))).toBe(committedTypes);
  });

  it.skipIf(!required && !hasUv)("openapi.json is the backend's current OpenAPI document", () => {
    expect(exportOpenApi()).toBe(committedDocument);
  }, 120_000);

  it("the document describes the routes the shell uses", () => {
    const paths = Object.keys((JSON.parse(committedDocument) as { paths: Record<string, unknown> }).paths);
    for (const path of ["/api/v1/auth/session", "/api/v1/admin/api-keys", "/api/v1/info"]) expect(paths).toContain(path);
  });
});
