import { i18n } from "@lingui/core";

/** Date and time of an ISO 8601 string in the user's language and time zone; the input itself when it is no date. */
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(i18n.locale || "de", { dateStyle: "medium", timeStyle: "medium" }).format(date);
}

/** `datetime-local` value (no zone, the browser's time) to the ISO 8601 string with a zone the API needs. */
export function localInputToIso(value: string): string | undefined {
  if (value === "") return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

/** Pretty-printed JSON for display; never throws (a value that cannot be written is shown as text). */
export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "";
  } catch {
    return String(value);
  }
}
