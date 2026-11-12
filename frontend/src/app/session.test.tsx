import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { apiFetch, setCsrfToken } from "../api/client";
import { INFO, jsonResponse, problemResponse, renderApp, SESSION, stubFetch, testQueryClient } from "../test-utils";
import { createQueryClient, shouldRetry } from "./queryClient";
import { safeRedirect } from "./router";
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

  it("a request that finds the sign-in gone ends the session and drops the previous user's data", async () => {
    stubFetch({
      "GET /api/v1/auth/session": () => jsonResponse(SESSION),
      "GET /api/v1/info": () => jsonResponse(INFO),
      "GET /api/v1/settings": signedOut,
    });
    const queryClient = testQueryClient();
    const uninstall = installAuthGuard(queryClient);
    const { router } = renderApp("/protocol", queryClient);
    expect(await screen.findByRole("heading", { name: "Protokoll" })).toBeInTheDocument();
    queryClient.setQueryData(["events"], ["private"]);

    await expect(apiFetch("/api/v1/settings")).rejects.toMatchObject({ status: 401 });

    expect(await screen.findByLabelText("API-Token")).toBeInTheDocument();
    expect(router.state.location.search).toEqual({ redirect: "/protocol" });
    expect(queryClient.getQueryData(["events"])).toBeUndefined();
    expect(queryClient.getQueryData(SESSION_KEY)).toBeNull();
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
