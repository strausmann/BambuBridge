import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { CSRF_HEADER, setCsrfToken } from "../api/client";
import { INFO, jsonResponse, problemResponse, renderApp, SESSION, stubFetch } from "../test-utils";

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  setCsrfToken(null);
});

const signedOut = () => problemResponse(401, "not_authenticated", "Authentication required");

describe("sign-in", () => {
  it("a token sign-in opens the session and leads into the shell", async () => {
    let signedIn = false;
    const calls = stubFetch({
      "GET /api/v1/auth/session": () => (signedIn ? jsonResponse(SESSION) : signedOut()),
      "POST /api/v1/auth/session": () => {
        signedIn = true;
        return jsonResponse(SESSION, { status: 201 });
      },
      "GET /api/v1/info": () => jsonResponse(INFO),
      "DELETE /api/v1/auth/session": () => new Response(null, { status: 204 }),
    });
    const user = userEvent.setup();
    const { router } = renderApp("/providers");

    // Signed out: the sign-in is shown and remembers where the visitor wanted to go.
    const field = await screen.findByLabelText("API-Token");
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(router.state.location.search).toEqual({ redirect: "/providers" });

    await user.type(field, "bb_test-token");
    await user.click(screen.getByRole("button", { name: "Anmelden" }));

    // The session is set: the shell with the remembered page and the user's name.
    expect(await screen.findByRole("heading", { name: "Anbieter" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/providers");
    expect(screen.getByTestId("signed-in-user")).toHaveTextContent("Angemeldet als admin");
    const post = calls.find((call) => call.method === "POST")!;
    expect(post.body).toEqual({ token: "bb_test-token" });

    // The CSRF token of the sign-in answer goes out with the next state-changing request.
    await user.click(screen.getByRole("button", { name: "Abmelden" }));
    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
    expect(calls.find((call) => call.method === "DELETE")!.headers.get(CSRF_HEADER)).toBe("csrf-1");
    expect(await screen.findByLabelText("API-Token")).toBeInTheDocument();
  });

  it("a rejected token shows an error, clears the field and stays on the sign-in", async () => {
    stubFetch({
      "GET /api/v1/auth/session": signedOut,
      "POST /api/v1/auth/session": () => problemResponse(401, "invalid_token", "Invalid API token"),
    });
    const user = userEvent.setup();
    const { router } = renderApp("/sign-in");

    const field = await screen.findByLabelText("API-Token");
    await user.type(field, "wrong");
    await user.click(screen.getByRole("button", { name: "Anmelden" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Dieses Token wurde nicht akzeptiert.");
    expect(field).toHaveValue("");
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(screen.queryByTestId("signed-in-user")).not.toBeInTheDocument();
  });

  it("names rate limiting, an unreachable server and a disabled user", async () => {
    const answers: (() => Response | Promise<Response>)[] = [
      () => problemResponse(429, "rate_limited", "Too many sign-in attempts"),
      () => Promise.reject(new TypeError("Failed to fetch")),
      () => problemResponse(401, "user_disabled", "User disabled"),
      () => problemResponse(500, "internal_error", "Internal error"),
    ];
    stubFetch({ "GET /api/v1/auth/session": signedOut, "POST /api/v1/auth/session": () => answers.shift()!() });
    const user = userEvent.setup();
    renderApp("/sign-in");

    const field = await screen.findByLabelText("API-Token");
    for (const expected of [
      "Zu viele Versuche. Warte eine Minute und versuche es erneut.",
      "Der Server ist nicht erreichbar.",
      "Dieser Benutzer ist deaktiviert.",
      "Etwas ist schiefgegangen.",
    ]) {
      await user.type(field, "x");
      await user.click(screen.getByRole("button", { name: "Anmelden" }));
      await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(expected));
    }
  });

  it("does not send an empty token", async () => {
    const calls = stubFetch({ "GET /api/v1/auth/session": signedOut });
    const user = userEvent.setup();
    renderApp("/sign-in");
    await screen.findByLabelText("API-Token");
    await user.click(screen.getByRole("button", { name: "Anmelden" }));
    expect(calls.filter((call) => call.method === "POST")).toEqual([]);
  });

  it("single sign-on asks the server without a body and explains a refusal", async () => {
    let recognised = false;
    const calls = stubFetch({
      "GET /api/v1/auth/session": signedOut,
      "POST /api/v1/auth/session": () => (recognised ? jsonResponse({ ...SESSION, user: "Ada", identity_provider: "pangolin_header", identity_subject: "ada" }, { status: 201 }) : signedOut()),
      "GET /api/v1/info": () => jsonResponse(INFO),
    });
    const user = userEvent.setup();
    renderApp("/sign-in");

    const sso = await screen.findByRole("button", { name: "Mit einmaliger Anmeldung (SSO) fortfahren" });
    await user.click(sso);
    expect(await screen.findByRole("alert")).toHaveTextContent("Die einmalige Anmeldung hat dich nicht erkannt.");
    expect(calls.find((call) => call.method === "POST")!.body).toBeUndefined();

    recognised = true;
    await user.click(sso);
    expect(await screen.findByTestId("signed-in-user")).toHaveTextContent("Angemeldet als Ada");
  });
});
