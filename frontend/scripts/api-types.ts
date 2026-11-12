import openapiTS, { astToString } from "openapi-typescript";

const HEADER = `/**
 * Generated from openapi.json by \`pnpm gen:api\` (openapi-typescript). Do not edit by hand.
 */

`;

/** The TypeScript source of `src/api/schema.gen.ts` for an OpenAPI document. */
export async function renderApiTypes(schema: unknown): Promise<string> {
  // The generator mutates its input; hand it a copy.
  const ast = await openapiTS(structuredClone(schema) as Parameters<typeof openapiTS>[0]);
  return HEADER + astToString(ast);
}
