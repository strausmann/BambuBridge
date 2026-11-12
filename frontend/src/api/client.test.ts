import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  apiFetch,
  AuthRequiredError,
  CSRF_HEADER,
  resetVersionSignal,
  setCsrfToken,
  setOnAuthRequired,
  subscribeVersionMismatch,
  VERSION_HEADER,
  VersionMismatchError,
} from "./client";

type FetchArgs = [input: string, init: RequestInit];

function json(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), { status: 200, ...init, headers: { "Content-Type": "application/json", ...init.headers } });
}

function problem(status: number, error_code: string, title: string, detail?: string): Response {
  return new Response(JSON.stringify({ type: "about:blank", title, status, detail, error_code, extensions: {} }), {
    status,
    headers: { "Content-Type": "application/problem+json" },
  });
}

const fetchMock = vi.fn<(...args: FetchArgs) => Promise<Response>>();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
  setCsrfToken(null);
  setOnAuthRequired(null);
  resetVersionSignal();
});

function sent(call = 0): { path: string; init: RequestInit; headers: Headers } {
  const [path, init] = fetchMock.mock.calls[call]!;
  return { path, init, headers: new Headers(init.headers) };
}

describe("apiFetch", () => {
  it("returns the parsed body and never follows a redirect on its own", async () => {
    fetchMock.mockResolvedValue(json({ name: "BambuBridge" }));
    await expect(apiFetch("/api/v1/info")).resolves.toEqual({ name: "BambuBridge" });
    const { path, init, headers } = sent();
    expect(path).toBe("/api/v1/info");
    expect(init.redirect).toBe("manual");
    expect(init.credentials).toBe("same-origin");
    expect(init.method).toBe("GET");
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("sends the CSRF token with state-changing requests only", async () => {
    setCsrfToken("csrf-value");
    fetchMock.mockImplementation(() => Promise.resolve(json({})));
    await apiFetch("/api/v1/info");
    expect(sent(0).headers.has(CSRF_HEADER)).toBe(false);
    for (const method of ["POST", "PUT", "PATCH", "DELETE"]) await apiFetch("/api/v1/x", { method });
    for (let call = 1; call <= 4; call += 1) expect(sent(call).headers.get(CSRF_HEADER)).toBe("csrf-value");
  });

  it("sends no CSRF header without a session", async () => {
    fetchMock.mockResolvedValue(json({}));
    await apiFetch("/api/v1/x", { method: "POST" });
    expect(sent().headers.has(CSRF_HEADER)).toBe(false);
  });

  it("serialises `json` and keeps headers the caller set", async () => {
    fetchMock.mockResolvedValue(json({}));
    await apiFetch("/api/v1/x", { method: "POST", json: { a: 1 }, headers: { "X-Extra": "1" } });
    const { init, headers } = sent();
    expect(init.body).toBe('{"a":1}');
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("X-Extra")).toBe("1");
  });

  it("returns undefined for 204", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiFetch("/api/v1/auth/session", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("throws AuthRequiredError for 401 and tells the registered handler", async () => {
    const handler = vi.fn();
    setOnAuthRequired(handler);
    fetchMock.mockResolvedValue(problem(401, "not_authenticated", "Authentication required"));
    const error = await apiFetch("/api/v1/settings").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(AuthRequiredError);
    expect(error).toMatchObject({ status: 401, code: "not_authenticated" });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("throws AuthRequiredError for a redirect to a login page (opaque redirect)", async () => {
    const handler = vi.fn();
    setOnAuthRequired(handler);
    const redirect = new Response(null, { status: 200 });
    Object.defineProperty(redirect, "type", { value: "opaqueredirect" });
    Object.defineProperty(redirect, "status", { value: 0 });
    Object.defineProperty(redirect, "ok", { value: false });
    fetchMock.mockResolvedValue(redirect);
    const error = await apiFetch("/api/v1/settings").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(AuthRequiredError);
    expect(error).toMatchObject({ code: "login_redirect" });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("treats a 200 with an HTML body (a proxy's login page) as sign-in required", async () => {
    const handler = vi.fn();
    setOnAuthRequired(handler);
    fetchMock.mockResolvedValue(new Response("<html>login</html>", { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } }));
    const error = await apiFetch("/api/v1/settings").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(AuthRequiredError);
    expect(error).toMatchObject({ code: "unexpected_content" });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("an answer that is neither JSON nor HTML is an error of its own, not a missing sign-in", async () => {
    const handler = vi.fn();
    setOnAuthRequired(handler);
    fetchMock.mockResolvedValue(new Response("ok", { status: 200, headers: { "Content-Type": "text/plain" } }));
    const error = await apiFetch("/api/v1/settings").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeInstanceOf(AuthRequiredError);
    expect(error).toMatchObject({ status: 200, code: "unexpected_content" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("returns undefined for an empty 2xx body, whatever its content type", async () => {
    fetchMock.mockResolvedValueOnce(new Response("", { status: 200 }));
    await expect(apiFetch("/api/v1/thing", { method: "POST" })).resolves.toBeUndefined();
    fetchMock.mockResolvedValueOnce(new Response("", { status: 202, headers: { "Content-Type": "application/json" } }));
    await expect(apiFetch("/api/v1/thing", { method: "POST" })).resolves.toBeUndefined();
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 205 }));
    await expect(apiFetch("/api/v1/thing", { method: "POST" })).resolves.toBeUndefined();
  });

  it("a JSON answer that does not parse is an error, not a missing sign-in", async () => {
    fetchMock.mockResolvedValue(new Response("{not json", { status: 200, headers: { "Content-Type": "application/json" } }));
    const error = await apiFetch("/api/v1/settings").catch((e: unknown) => e);
    expect(error).not.toBeInstanceOf(AuthRequiredError);
    expect(error).toMatchObject({ status: 200, code: "unexpected_content" });
  });

  it("skipAuthHandler: the 401 is thrown but the handler stays quiet", async () => {
    const handler = vi.fn();
    setOnAuthRequired(handler);
    fetchMock.mockResolvedValue(problem(401, "invalid_token", "Invalid API token"));
    await expect(apiFetch("/api/v1/auth/session", { method: "POST", json: { token: "x" }, skipAuthHandler: true })).rejects.toBeInstanceOf(
      AuthRequiredError,
    );
    expect(handler).not.toHaveBeenCalled();
  });

  it("reads problem details: code, detail (falling back to the title) and extensions", async () => {
    fetchMock.mockResolvedValueOnce(problem(403, "bootstrap_closed", "Bootstrap is closed"));
    const first = await apiFetch("/x").catch((e: unknown) => e);
    expect(first).toBeInstanceOf(ApiError);
    expect(first).not.toBeInstanceOf(AuthRequiredError);
    expect(first).toMatchObject({ status: 403, code: "bootstrap_closed", detail: "Bootstrap is closed" });

    fetchMock.mockResolvedValueOnce(problem(429, "rate_limited", "Too many sign-in attempts", "Retry after 12 seconds."));
    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 429, detail: "Retry after 12 seconds." });
  });

  it("falls back to the status when the error body is not a problem", async () => {
    fetchMock.mockResolvedValueOnce(new Response("gateway down", { status: 502 }));
    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 502, code: null, detail: "HTTP 502" });
    fetchMock.mockResolvedValueOnce(new Response("{broken", { status: 500, headers: { "Content-Type": "application/json" } }));
    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 500, code: null });
  });

  it("only requests a path on this origin: one leading slash, no backslash, no scheme", async () => {
    setCsrfToken("csrf-1");
    for (const path of ["//evil.example/api", "https://evil.example/api", "/\\evil.example/api", "api/v1/info", "", "\\\\evil.example", "/api\\..\\x", " /api/v1/info", "/\t/evil.example"]) {
      await expect(apiFetch(path, { method: "POST" }), JSON.stringify(path)).rejects.toBeInstanceOf(TypeError);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reports an unreachable server as status 0", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });
});

describe("version signal", () => {
  it("stays quiet while the server reports this build", async () => {
    const listener = vi.fn();
    subscribeVersionMismatch(listener);
    fetchMock.mockResolvedValue(json({}, { headers: { [VERSION_HEADER]: __APP_VERSION__ } }));
    await apiFetch("/api/v1/info");
    expect(listener).not.toHaveBeenCalled();
  });

  it("signals another server version once, also on error responses", async () => {
    const listener = vi.fn<(signal: VersionMismatchError) => void>();
    const unsubscribe = subscribeVersionMismatch(listener);
    fetchMock.mockImplementation(() => Promise.resolve(json({}, { headers: { [VERSION_HEADER]: "9.9.9+abc" } })));
    await apiFetch("/api/v1/info");
    await apiFetch("/api/v1/info");
    expect(listener).toHaveBeenCalledTimes(1);
    const signal = listener.mock.calls[0]![0];
    expect(signal).toBeInstanceOf(VersionMismatchError);
    expect(signal).toMatchObject({ expected: __APP_VERSION__, actual: "9.9.9+abc" });

    const failing = new Response(JSON.stringify({ title: "x", status: 500 }), { status: 500, headers: { "Content-Type": "application/problem+json", [VERSION_HEADER]: "10.0.0+def" } });
    fetchMock.mockResolvedValueOnce(failing);
    await apiFetch("/api/v1/info").catch(() => undefined);
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    resetVersionSignal();
    await apiFetch("/api/v1/info");
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("ignores responses without the header", async () => {
    const listener = vi.fn();
    subscribeVersionMismatch(listener);
    fetchMock.mockResolvedValue(json({}));
    await apiFetch("/healthz");
    expect(listener).not.toHaveBeenCalled();
  });
});
