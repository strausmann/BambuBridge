import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, setCsrfToken } from "../api/client";
import { INFO, jsonResponse, problemResponse, renderApp, SESSION, stubFetch, testQueryClient } from "../test-utils";
import { createQueryClient, shouldRetry } from "./queryClient";
import { createFirstAdminToken, safeRedirect } from "./router";
import { installAuthGuard, SESSION_KEY } from "./session";
import { ApiError } from "../api/client";

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  setCsrfToken(null);
});

const signedOut = () => problemResponse(401, "not_authenticated", "Authentication required");

describe("root layout", () => {
  it("shows a splash until the server answered", async () => {
    let answer!: (response: Response) => void;
    stubFetch({
      "GET /api/v1/auth/session": () => new Promise<Response>((resolve) => (answer = resolve)),
      "GET /api/v1/info": () => jsonResponse(INFO),
    });
    renderApp("/");
    expect(await screen.findByRole("status")).toHaveTextContent("Lädt …");
    answer(jsonResponse(SESSION));
    expect(await screen.findByRole("heading", { name: "Übersicht" })).toBeInTheDocument();
  });

  it("tells an unreachable server from a missing sign-in and retries on request", async () => {
    let up = false;
    stubFetch({
      "GET /api/v1/auth/session": () => (up ? jsonResponse(SESSION) : problemResponse(503, "database_unavailable", "Database unavailable")),
      "GET /api/v1/info": () => jsonResponse(INFO),
    });
    const user = userEvent.setup();
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Der Server ist nicht erreichbar." })).toBeInTheDocument();
    expect(screen.queryByLabelText("API-Token")).not.toBeInTheDocument();
    up = true;
    await user.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    expect(await screen.findByRole("heading", { name: "Übersicht" })).toBeInTheDocument();
  });

  it("a signed-in visitor on the sign-in page is sent on, never to another site", async () => {
    stubFetch({ "GET /api/v1/auth/session": () => jsonResponse(SESSION), "GET /api/v1/info": () => jsonResponse(INFO) });
    const { router } = renderApp("/sign-in?redirect=%2F%2Fevil.example%2Fx");
    expect(await screen.findByRole("heading", { name: "Übersicht" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
  });

  it("a signed-in visitor has no first-start screen", async () => {
    stubFetch({ "GET /api/v1/auth/session": () => jsonResponse(SESSION), "GET /api/v1/info": () => jsonResponse(INFO) });
    const { router } = renderApp("/bootstrap");
    expect(await screen.findByRole("heading", { name: "Übersicht" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
  });

  it("a request that finds the sign-in gone drops the previous user's data and continues at /auth/continue", async () => {
    stubFetch({
      "GET /api/v1/auth/session": () => jsonResponse(SESSION),
      "GET /api/v1/info": () => jsonResponse(INFO),
      "GET /api/v1/settings": signedOut,
    });
    window.history.replaceState(null, "", "/protocol?tab=2");
    const queryClient = testQueryClient();
    const navigate = vi.fn();
    const uninstall = installAuthGuard(queryClient, navigate);
    renderApp("/protocol", queryClient);
    expect(await screen.findByRole("heading", { name: "Protokoll" })).toBeInTheDocument();
    queryClient.setQueryData(["events"], ["private"]);

    await expect(apiFetch("/api/v1/settings")).rejects.toMatchObject({ status: 401 });

    // A full page load to the server's sign-in hop (an SSO proxy may sign in again on the way),
    // never to "/": the service worker would answer that from its cache.
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/auth/continue?next=%2Fprotocol%3Ftab%3D2");
    // Until the browser has left, a neutral splash: no shell with emptied data, no sign-in form.
    expect(await screen.findByRole("status")).toHaveTextContent("Lädt …");
    expect(screen.queryByLabelText("API-Token")).not.toBeInTheDocument();
    expect(queryClient.getQueryData(["events"])).toBeUndefined();
    expect(queryClient.getQueryData(SESSION_KEY)).toBeNull();

    // A second refused request while leaving does not start a second navigation.
    await expect(apiFetch("/api/v1/settings")).rejects.toMatchObject({ status: 401 });
    expect(navigate).toHaveBeenCalledTimes(1);
    uninstall();
    window.history.replaceState(null, "", "/");
  });

  it("a session read that finds an open session gone continues at /auth/continue as well", async () => {
    let signedIn = true;
    stubFetch({
      "GET /api/v1/auth/session": () => (signedIn ? jsonResponse(SESSION) : signedOut()),
      "GET /api/v1/info": () => jsonResponse(INFO),
    });
    window.history.replaceState(null, "", "/providers");
    const queryClient = testQueryClient();
    const navigate = vi.fn();
    const uninstall = installAuthGuard(queryClient, navigate);
    renderApp("/providers", queryClient);
    expect(await screen.findByRole("heading", { name: "Anbieter" })).toBeInTheDocument();
    signedIn = false;
    await queryClient.refetchQueries({ queryKey: SESSION_KEY });
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/auth/continue?next=%2Fproviders"));
    uninstall();
    window.history.replaceState(null, "", "/");
  });

  it("a visitor who was never signed in gets the sign-in page directly, without the hop", async () => {
    stubFetch({ "GET /api/v1/auth/session": signedOut, "GET /api/v1/info": () => jsonResponse(INFO) });
    const queryClient = testQueryClient();
    const navigate = vi.fn();
    const uninstall = installAuthGuard(queryClient, navigate);
    const { router } = renderApp("/protocol", queryClient);
    expect(await screen.findByLabelText("API-Token")).toBeInTheDocument();
    expect(router.state.location.search).toEqual({ redirect: "/protocol" });
    expect(navigate).not.toHaveBeenCalled();
    uninstall();
  });

  it("another identity behind the same cookie does not inherit cached data", async () => {
    let current: Record<string, unknown> = SESSION;
    stubFetch({ "GET /api/v1/auth/session": () => jsonResponse(current), "GET /api/v1/info": () => jsonResponse(INFO) });
    const queryClient = testQueryClient();
    renderApp("/", queryClient);
    expect(await screen.findByTestId("signed-in-user")).toHaveTextContent("admin");
    queryClient.setQueryData(["events"], ["private"]);

    current = { ...SESSION, user: "Ada", identity_provider: "pangolin_header", identity_subject: "ada" };
    await queryClient.refetchQueries({ queryKey: SESSION_KEY });
    await waitFor(() => expect(screen.getByTestId("signed-in-user")).toHaveTextContent("Ada"));
    expect(queryClient.getQueryData(["events"])).toBeUndefined();
  });

  it("an unknown path shows 'not found' inside the app", async () => {
    stubFetch({ "GET /api/v1/auth/session": () => jsonResponse(SESSION), "GET /api/v1/info": () => jsonResponse(INFO) });
    renderApp("/does-not-exist");
    expect(await screen.findByRole("heading", { name: "Seite nicht gefunden" })).toBeInTheDocument();
  });
});

describe("safeRedirect", () => {
  it("keeps plain paths on this site", () => {
    expect(safeRedirect("/providers")).toBe("/providers");
    expect(safeRedirect("/settings/access?tab=1")).toBe("/settings/access?tab=1");
  });

  it("returns the normalised path, so what was checked is what is used", () => {
    expect(safeRedirect("/settings/../providers")).toBe("/providers");
    expect(safeRedirect("/providers#top")).toBe("/providers#top");
    expect(safeRedirect("/apiary")).toBe("/apiary");
    expect(safeRedirect("/docs-of-mine")).toBe("/docs-of-mine");
  });

  it("rejects dot segments and backslashes that resolve to //host, in every spelling", () => {
    for (const value of [
      "/..//host/p",
      "/.//host/p",
      "/x/..//host/p",
      "/x/../..//host/p",
      "/.\\/host/p",
      "/..\\/host/p",
      "/\\host/p",
      "/x\\..\\..\\/host",
      "/%2e%2e//host/p",
      "/%2E%2E//host/p",
      "/.%2e//host/p",
      "/%2e//host/p",
      "/%5chost/p",
      "/%5Chost/p",
      "/x/%5c/host",
      "/a\\b",
    ]) {
      expect(safeRedirect(value), value).toBeUndefined();
    }
  });

  it("rejects paths the server owns and the public pages behind dot segments", () => {
    for (const value of ["/api", "/api/", "/api/v1/info", "/auth/continue", "/auth", "/docs", "/docs/", "/docs/oauth2-redirect", "/openapi.json", "/x/../api/v1/info", "/%2e/auth/x", "/x/../sign-in", "/x/../bootstrap?a=1", "/sign-in#x"]) {
      expect(safeRedirect(value), value).toBeUndefined();
    }
  });

  it("rejects reserved paths in any spelling of case and percent-encoding, and an encoded //", () => {
    for (const value of [
      "/API/v1/info",
      "/Api",
      "/%61pi/v1/info",
      "/%41PI/v1/info",
      "/a%70i/",
      "/AUTH/continue",
      "/%61uth/continue",
      "/Docs",
      "/d%6fcs",
      "/OpenAPI.json",
      "/openapi%2Ejson",
      "/Sign-In",
      "/sign%2Din",
      "/BOOTSTRAP",
      "/api%2Fv1%2Finfo",
      "/%2F%2Fevil.example/p",
      "/%2f/evil.example",
      "/x%2f%2fevil.example",
      "/x//y",
      "/%E0%A4%A",
      "/%",
    ]) {
      expect(safeRedirect(value), value).toBeUndefined();
    }
  });

  it("keeps ordinary encoded characters in a path", () => {
    expect(safeRedirect("/settings/a%20b")).toBe("/settings/a%20b");
    expect(safeRedirect("/providers?q=%2F%2Fx&api=/api/")).toBe("/providers?q=%2F%2Fx&api=/api/");
  });

  it("rejects other hosts, schemes, control characters and the public pages", () => {
    for (const value of ["//evil.example", "/\\evil.example", "https://evil.example", "javascript:alert(1)", "/\t/evil.example", "/sign-in", "/sign-in?redirect=/x", "/bootstrap", "", 7, null, undefined]) {
      expect(safeRedirect(value), String(value)).toBeUndefined();
    }
  });
});

describe("query client", () => {
  it("does not retry a 4xx, retries a 5xx or a dropped connection twice", () => {
    expect(shouldRetry(0, new ApiError(404, "not_found", "x"))).toBe(false);
    expect(shouldRetry(0, new ApiError(503, null, "x"))).toBe(true);
    expect(shouldRetry(1, new ApiError(0, "network_error", "x"))).toBe(true);
    expect(shouldRetry(2, new ApiError(0, "network_error", "x"))).toBe(false);
    expect(createQueryClient().getDefaultOptions().queries?.staleTime).toBe(15_000);
  });
});

describe("createFirstAdminToken", () => {
  it("returns the token of the answer", async () => {
    stubFetch({ "POST /api/v1/admin/api-keys": () => jsonResponse({ token: "bb_new" }, { status: 201 }) });
    await expect(createFirstAdminToken("key")).resolves.toBe("bb_new");
  });

  it("fails when the answer holds no token, instead of showing an empty one", async () => {
    for (const body of [{}, { token: "" }, { token: 7 }, { token: null }, null, []]) {
      stubFetch({ "POST /api/v1/admin/api-keys": () => jsonResponse(body, { status: 201 }) });
      await expect(createFirstAdminToken("key"), JSON.stringify(body)).rejects.toMatchObject({ code: "unexpected_content" });
    }
    stubFetch({ "POST /api/v1/admin/api-keys": () => new Response("", { status: 201 }) });
    await expect(createFirstAdminToken("key")).rejects.toMatchObject({ code: "unexpected_content" });
  });
});
