/**
 * Thin fetch wrapper for the backend API (same origin, so the session cookie is enough).
 * Types come from `schema.gen.ts`, generated from the backend's OpenAPI (`pnpm gen:api`).
 */

export const CSRF_HEADER = "X-BambuBridge-CSRF";
export const VERSION_HEADER = "X-BambuBridge-Version";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** An error response from the API, or `status` 0 when the server could not be reached. */
export class ApiError extends Error {
  readonly status: number;
  /** Machine-readable `error_code` of the problem; null when the body has none. */
  readonly code: string | null;
  readonly detail: string;
  /** The problem's `extensions`; null when none. */
  readonly extensions: Record<string, unknown> | null;

  constructor(status: number, code: string | null, detail: string, extensions: Record<string, unknown> | null = null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.extensions = extensions;
  }
}

/**
 * The request needs a sign-in: a 401, a redirect to a login page (a proxy in front of the API
 * answers with one once its own session ended; `redirect: "manual"` makes it visible instead of
 * following it), or a "successful" answer that is an HTML page (the login page itself).
 */
export class AuthRequiredError extends ApiError {
  constructor(code: string | null, detail: string, status = 401) {
    super(status, code, detail);
    this.name = "AuthRequiredError";
  }
}

/** The server runs another build than this page (`X-BambuBridge-Version` differs). A signal, never thrown. */
export class VersionMismatchError extends Error {
  readonly expected: string;
  readonly actual: string;

  constructor(expected: string, actual: string) {
    super(`server version ${actual} differs from this page (${expected})`);
    this.name = "VersionMismatchError";
    this.expected = expected;
    this.actual = actual;
  }
}

let csrfToken: string | null = null;
let onAuthRequired: (() => void) | null = null;
const versionListeners = new Set<(signal: VersionMismatchError) => void>();
let signalledVersion: string | null = null;

/** The session state registers the CSRF token it got from the session endpoint. */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Registers what happens when any request finds the sign-in gone (the shell shows the sign-in). */
export function setOnAuthRequired(handler: (() => void) | null): void {
  onAuthRequired = handler;
}

/** Called once per differing server version; what to do with it (update, reload) is the listener's part. */
export function subscribeVersionMismatch(listener: (signal: VersionMismatchError) => void): () => void {
  versionListeners.add(listener);
  return () => void versionListeners.delete(listener);
}

/** Forget which server version was already signalled (tests, and after an update was applied). */
export function resetVersionSignal(): void {
  signalledVersion = null;
}

function checkVersion(response: Response): void {
  const actual = response.headers.get(VERSION_HEADER);
  if (!actual || actual === __APP_VERSION__ || actual === signalledVersion) return;
  signalledVersion = actual;
  const signal = new VersionMismatchError(__APP_VERSION__, actual);
  [...versionListeners].forEach((listener) => listener(signal));
}

export type ApiInit = RequestInit & {
  /** Sent as the JSON body. */
  json?: unknown;
  /** A missing sign-in is thrown without running the registered handler (the sign-in form asks this itself). */
  skipAuthHandler?: boolean;
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJson(response: Response): boolean {
  return /json/i.test(response.headers.get("Content-Type") ?? "");
}

function isHtml(response: Response): boolean {
  return /^\s*text\/html\b/i.test(response.headers.get("Content-Type") ?? "");
}

async function readJson(response: Response): Promise<unknown> {
  if (!isJson(response)) return undefined;
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

/** Errors are RFC 9457 problem details with a stable `error_code`. */
function parseProblem(status: number, body: unknown): { code: string | null; detail: string; extensions: Record<string, unknown> | null } {
  const fallback = `HTTP ${status}`;
  if (!isObject(body)) return { code: null, detail: fallback, extensions: null };
  const code = typeof body.error_code === "string" ? body.error_code : null;
  const detail = typeof body.detail === "string" ? body.detail : typeof body.title === "string" ? body.title : fallback;
  const extensions = isObject(body.extensions) && Object.keys(body.extensions).length > 0 ? body.extensions : null;
  return { code, detail, extensions };
}

/**
 * `path` must be a path on this origin: one leading slash, then no second slash, no backslash
 * (browsers read it as a slash) and no control character (browsers drop them). The session cookie
 * and the CSRF token ride on every request, so a value that could name another host is a
 * programming error and is refused before anything is sent.
 */
function assertOwnPath(path: string): void {
  // eslint-disable-next-line no-control-regex
  if (!/^\/(?![/\\])/.test(path) || path.includes("\\") || /[\u0000-\u001f\u007f]/.test(path)) {
    throw new TypeError("apiFetch needs a path on this origin, starting with a single slash");
  }
}

export async function apiFetch<T>(path: string, init: ApiInit = {}): Promise<T> {
  assertOwnPath(path);
  const { json, skipAuthHandler = false, headers: initHeaders, ...rest } = init;
  const method = (rest.method ?? "GET").toUpperCase();
  const headers = new Headers(initHeaders);
  if (json !== undefined) headers.set("Content-Type", "application/json");
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (UNSAFE_METHODS.has(method) && csrfToken) headers.set(CSRF_HEADER, csrfToken);

  let response: Response;
  try {
    response = await fetch(path, {
      ...rest,
      method,
      headers,
      credentials: "same-origin",
      redirect: "manual",
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, "network_error", "Network error");
  }
  checkVersion(response);

  const authRequired = (error: AuthRequiredError): AuthRequiredError => {
    if (!skipAuthHandler) onAuthRequired?.();
    return error;
  };

  if (response.type === "opaqueredirect") throw authRequired(new AuthRequiredError("login_redirect", "Sign-in required"));
  if (!response.ok) {
    const { code, detail, extensions } = parseProblem(response.status, await readJson(response));
    if (response.status === 401) throw authRequired(new AuthRequiredError(code, detail));
    throw new ApiError(response.status, code, detail, extensions);
  }
  if (response.status === 204) return undefined as T;
  // The API never answers with a page: HTML here is the login page of a proxy in front of it.
  if (isHtml(response)) throw authRequired(new AuthRequiredError("unexpected_content", "Sign-in required"));
  const text = await response.text();
  if (text === "") return undefined as T;
  const unexpected = () => new ApiError(response.status, "unexpected_content", "Unexpected answer from the server");
  if (!isJson(response)) throw unexpected();
  try {
    return JSON.parse(text) as T;
  } catch {
    throw unexpected();
  }
}
