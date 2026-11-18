import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { apiFetch, CSRF_HEADER, setCsrfToken } from "../api/client";
import { SESSION_KEY } from "../app/session";
import { INFO, jsonResponse, problemResponse, renderApp, SESSION, stubFetch, testQueryClient } from "../test-utils";

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
      "POST /api/v1/auth/session": () => (recognised ? jsonResponse({ ...SESSION, identity_provider: "pangolin_header", identity_subject: "ada" }, { status: 201 }) : signedOut()),
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
    expect(await screen.findByTestId("signed-in-user")).toHaveTextContent("Angemeldet als ada");
  });

  it("keeps the typed token when the failure is not about the token (no answer, rate limit, server error)", async () => {
    const answers: (() => Response | Promise<Response>)[] = [
      () => Promise.reject(new TypeError("Failed to fetch")),
      () => problemResponse(429, "rate_limited", "Too many sign-in attempts"),
      () => problemResponse(503, "database_unavailable", "Database unavailable"),
    ];
    stubFetch({ "GET /api/v1/auth/session": signedOut, "POST /api/v1/auth/session": () => answers.shift()!() });
    const user = userEvent.setup();
    renderApp("/sign-in");

    const field = await screen.findByLabelText("API-Token");
    await user.type(field, "bb_typed-once");
    for (const expected of ["Der Server ist nicht erreichbar.", "Zu viele Versuche.", "Etwas ist schiefgegangen."]) {
      await user.click(screen.getByRole("button", { name: "Anmelden" }));
      await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(expected));
      expect(field).toHaveValue("bb_typed-once");
    }
  });

  it("after a failed sign-in the focus is back in the token field", async () => {
    stubFetch({
      "GET /api/v1/auth/session": signedOut,
      "POST /api/v1/auth/session": () => problemResponse(401, "invalid_token", "Invalid API token"),
    });
    const user = userEvent.setup();
    renderApp("/sign-in");

    const field = await screen.findByLabelText("API-Token");
    await user.type(field, "wrong");
    await user.click(screen.getByRole("button", { name: "Anmelden" }));
    await screen.findByRole("alert");
    await waitFor(() => expect(field).toHaveFocus());
  });

  it("after a failed single sign-on the focus stays on its button", async () => {
    stubFetch({ "GET /api/v1/auth/session": signedOut, "POST /api/v1/auth/session": signedOut });
    const user = userEvent.setup();
    renderApp("/sign-in");
    const sso = await screen.findByRole("button", { name: "Mit einmaliger Anmeldung (SSO) fortfahren" });
    await user.click(sso);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Die einmalige Anmeldung hat dich nicht erkannt."));
    await waitFor(() => expect(sso).toHaveFocus());
    expect(screen.getByLabelText("API-Token")).not.toHaveFocus();
  });

  it("empties the token field once the sign-in went through", async () => {
    let signedIn = false;
    stubFetch({
      "GET /api/v1/auth/session": () => (signedIn ? jsonResponse(SESSION) : signedOut()),
      "POST /api/v1/auth/session": () => {
        signedIn = true;
        return jsonResponse(SESSION, { status: 201 });
      },
      "GET /api/v1/info": () => jsonResponse(INFO),
    });
    const user = userEvent.setup();
    renderApp("/sign-in");
    // The element outlives the screen (the test holds it, as a closure in the page could).
    const field = await screen.findByLabelText<HTMLInputElement>("API-Token");
    await user.type(field, "bb_secret-token");
    await user.click(screen.getByRole("button", { name: "Anmelden" }));
    await screen.findByTestId("signed-in-user");
    expect(field.value).toBe("");
    expect(field.getAttribute("value") ?? "").toBe("");
  });

  it("marks the pressed button as busy for assistive technology, and the mark does not move the label", async () => {
    let answer!: (response: Response) => void;
    stubFetch({
      "GET /api/v1/auth/session": signedOut,
      "POST /api/v1/auth/session": () => new Promise<Response>((resolve) => (answer = resolve)),
    });
    const user = userEvent.setup();
    renderApp("/sign-in");
    await user.type(await screen.findByLabelText("API-Token"), "t");
    const button = screen.getByRole("button", { name: "Anmelden" });
    const sso = screen.getByRole("button", { name: "Mit einmaliger Anmeldung (SSO) fortfahren" });
    expect(button).not.toHaveAttribute("aria-busy");
    await user.click(button);
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(sso).not.toHaveAttribute("aria-busy");
    // The mark hangs beside the label, out of the flow: appearing cannot shift the text.
    const mark = await screen.findByTestId("busy-mark", undefined, { timeout: 1500 });
    expect(mark.className).toContain("absolute");
    answer(problemResponse(401, "invalid_token", "Invalid API token"));
    await screen.findByRole("alert");
    expect(button).not.toHaveAttribute("aria-busy");
  });

  it("lets a password manager fill the token field", async () => {
    stubFetch({ "GET /api/v1/auth/session": signedOut });
    renderApp("/sign-in");
    expect(await screen.findByLabelText("API-Token")).toHaveAttribute("autocomplete", "current-password");
  });

  it("does not keep the token in the mutation cache, after a refused and after an accepted sign-in", async () => {
    let accept = false;
    let signedIn = false;
    stubFetch({
      "GET /api/v1/auth/session": () => (signedIn ? jsonResponse(SESSION) : signedOut()),
      "POST /api/v1/auth/session": () => {
        if (!accept) return problemResponse(503, "database_unavailable", "Database unavailable");
        signedIn = true;
        return jsonResponse(SESSION, { status: 201 });
      },
      "GET /api/v1/info": () => jsonResponse(INFO),
    });
    const queryClient = testQueryClient();
    const held = () => JSON.stringify(queryClient.getMutationCache().getAll().map((mutation) => mutation.state.variables));
    const user = userEvent.setup();
    renderApp("/sign-in", queryClient);

    await user.type(await screen.findByLabelText("API-Token"), "bb_secret-token");
    await user.click(screen.getByRole("button", { name: "Anmelden" }));
    await screen.findByRole("alert");
    await waitFor(() => expect(held()).not.toContain("bb_secret-token"));

    accept = true;
    await user.click(screen.getByRole("button", { name: "Anmelden" }));
    await screen.findByTestId("signed-in-user");
    await waitFor(() => expect(held()).not.toContain("bb_secret-token"));
  });

  it("a slow sign-in keeps the button's label and shows a busy mark after a moment, not at once", async () => {
    let answer!: (response: Response) => void;
    stubFetch({
      "GET /api/v1/auth/session": signedOut,
      "POST /api/v1/auth/session": () => new Promise<Response>((resolve) => (answer = resolve)),
    });
    const user = userEvent.setup();
    renderApp("/sign-in");

    await user.type(await screen.findByLabelText("API-Token"), "t");
    const button = screen.getByRole("button", { name: "Anmelden" });
    await user.click(button);
    expect(button).toHaveTextContent("Anmelden");
    expect(screen.queryByTestId("busy-mark")).not.toBeInTheDocument();
    expect(await screen.findByTestId("busy-mark", undefined, { timeout: 1500 })).toBeInTheDocument();
    expect(button).toHaveTextContent("Anmelden");

    answer(problemResponse(401, "invalid_token", "Invalid API token"));
    await screen.findByRole("alert");
    expect(screen.queryByTestId("busy-mark")).not.toBeInTheDocument();
  });
});

describe("sign-out", () => {
  function shell(signOut: () => Response | Promise<Response>) {
    const calls = stubFetch({
      "GET /api/v1/auth/session": () => jsonResponse(SESSION),
      "GET /api/v1/info": () => jsonResponse(INFO),
      "DELETE /api/v1/auth/session": signOut,
    });
    const queryClient = testQueryClient();
    const view = renderApp("/protocol", queryClient);
    return { calls, ...view };
  }

  for (const [name, answer] of [
    ["the server answers 503", () => problemResponse(503, "database_unavailable", "Database unavailable")],
    ["the server refuses with 403", () => problemResponse(403, "csrf_failed", "CSRF check failed")],
    ["the server cannot be reached", () => Promise.reject(new TypeError("Failed to fetch"))],
  ] as const) {
    it(`keeps the shell and says so when ${name}`, async () => {
      const { queryClient, router } = shell(answer);
      const user = userEvent.setup();
      expect(await screen.findByRole("heading", { name: "Protokoll" })).toBeInTheDocument();
      queryClient.setQueryData(["events"], ["private"]);

      await user.click(screen.getByRole("button", { name: "Abmelden" }));

      expect(await screen.findByRole("alert")).toHaveTextContent("Abmelden fehlgeschlagen, die Sitzung ist noch offen");
      expect(screen.getByRole("heading", { name: "Protokoll" })).toBeInTheDocument();
      expect(router.state.location.pathname).toBe("/protocol");
      expect(queryClient.getQueryData(SESSION_KEY)).toMatchObject({ user: "admin" });
      expect(queryClient.getQueryData(["events"])).toEqual(["private"]);
    });
  }

  it("a failed sign-out can be dismissed, and a second attempt that works ends the session", async () => {
    let up = false;
    const { calls } = shell(() => (up ? new Response(null, { status: 204 }) : problemResponse(503, "database_unavailable", "Database unavailable")));
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Protokoll" });

    await user.click(screen.getByRole("button", { name: "Abmelden" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Meldung schließen" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    up = true;
    await user.click(screen.getByRole("button", { name: "Abmelden" }));
    expect(await screen.findByLabelText("API-Token")).toBeInTheDocument();
    const deletes = calls.filter((call) => call.method === "DELETE");
    expect(deletes).toHaveLength(2);
    expect(deletes[1]!.headers.get(CSRF_HEADER)).toBe("csrf-1");
  });

  it("Escape closes the message as well, and either way the focus goes to the sign-out button", async () => {
    shell(() => problemResponse(503, "database_unavailable", "Database unavailable"));
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Protokoll" });
    const signOut = screen.getByRole("button", { name: "Abmelden" });

    await user.click(signOut);
    await screen.findByRole("alert");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(signOut).toHaveFocus();

    await user.click(signOut);
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Meldung schließen" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(signOut).toHaveFocus();
  });

  it("a refused sign-out reads the session again, so the retry carries the current CSRF token", async () => {
    let reads = 0;
    const calls = stubFetch({
      "GET /api/v1/auth/session": () => jsonResponse({ ...SESSION, csrf_token: reads++ === 0 ? "csrf-stale" : "csrf-fresh" }),
      "GET /api/v1/info": () => jsonResponse(INFO),
      "DELETE /api/v1/auth/session": (init) =>
        new Headers(init.headers).get(CSRF_HEADER) === "csrf-fresh" ? new Response(null, { status: 204 }) : problemResponse(403, "csrf_failed", "CSRF check failed"),
    });
    const user = userEvent.setup();
    renderApp("/protocol");
    await screen.findByRole("heading", { name: "Protokoll" });

    await user.click(screen.getByRole("button", { name: "Abmelden" }));
    await screen.findByRole("alert");
    await waitFor(() => expect(calls.filter((call) => call.method === "GET" && call.path === "/api/v1/auth/session")).toHaveLength(2));

    await user.click(screen.getByRole("button", { name: "Abmelden" }));
    expect(await screen.findByLabelText("API-Token")).toBeInTheDocument();
  });

  it("a sign-out that got no answer does not ask the unreachable server for the session", async () => {
    const { calls } = shell(() => Promise.reject(new TypeError("Failed to fetch")));
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Protokoll" });
    await user.click(screen.getByRole("button", { name: "Abmelden" }));
    await screen.findByRole("alert");
    expect(calls.filter((call) => call.method === "GET" && call.path === "/api/v1/auth/session")).toHaveLength(1);
  });

  it("ends the session here when the server says it is already gone (401)", async () => {
    const { queryClient } = shell(signedOut);
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "Protokoll" });
    queryClient.setQueryData(["events"], ["private"]);

    await user.click(screen.getByRole("button", { name: "Abmelden" }));

    expect(await screen.findByLabelText("API-Token")).toBeInTheDocument();
    expect(queryClient.getQueryData(["events"])).toBeUndefined();
  });

  it("a token sign-in shows the user's name; a single sign-on session shows the subject the provider reported", async () => {
    stubFetch({ "GET /api/v1/auth/session": () => jsonResponse(SESSION), "GET /api/v1/info": () => jsonResponse(INFO) });
    const first = renderApp("/");
    expect(await screen.findByTestId("signed-in-user")).toHaveTextContent("Angemeldet als admin");
    first.unmount();
    stubFetch({ "GET /api/v1/auth/session": () => jsonResponse({ ...SESSION, identity_provider: "pangolin_header", identity_subject: "ada@example.invalid" }), "GET /api/v1/info": () => jsonResponse(INFO) });
    renderApp("/");
    expect(await screen.findByTestId("signed-in-user")).toHaveTextContent("Angemeldet als ada@example.invalid");
  });

  it("names who is signed in on the sign-out button, also where the line is not shown", async () => {
    shell(() => new Response(null, { status: 204 }));
    expect(await screen.findByRole("button", { name: "Abmelden" })).toHaveAccessibleDescription("Angemeldet als admin");
  });
});

describe("first-start link", () => {
  const signedOutWith = (info: object) => stubFetch({ "GET /api/v1/auth/session": signedOut, "GET /api/v1/info": () => jsonResponse(info) });

  it("is offered while the server can still make the first admin token", async () => {
    signedOutWith({ ...INFO, bootstrap_open: true });
    renderApp("/sign-in");
    expect(await screen.findByRole("link", { name: "Erstes Admin-Token anlegen" })).toBeInTheDocument();
  });

  it("is gone once the first admin token exists", async () => {
    const calls = signedOutWith({ ...INFO, bootstrap_open: false });
    renderApp("/sign-in");
    await screen.findByLabelText("API-Token");
    await waitFor(() => expect(calls.some((call) => call.path === "/api/v1/info")).toBe(true));
    // Give the answer time to land: the link must not appear after it.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("link", { name: "Erstes Admin-Token anlegen" })).not.toBeInTheDocument();
    expect(screen.queryByText("Erster Start?")).not.toBeInTheDocument();
  });

  it("is not offered before the server has answered", async () => {
    stubFetch({ "GET /api/v1/auth/session": signedOut, "GET /api/v1/info": () => new Promise<Response>(() => undefined) });
    renderApp("/sign-in");
    await screen.findByLabelText("API-Token");
    expect(screen.queryByRole("link", { name: "Erstes Admin-Token anlegen" })).not.toBeInTheDocument();
  });
});

describe("session answers that arrive late", () => {
  it("a session read still under way when the sign-out completes does not bring the shell back", async () => {
    let late: ((response: Response) => void) | null = null;
    let reads = 0;
    const calls = stubFetch({
      "GET /api/v1/auth/session": () => (reads++ === 0 ? jsonResponse(SESSION) : new Promise<Response>((resolve) => (late = resolve))),
      "GET /api/v1/info": () => jsonResponse(INFO),
      "DELETE /api/v1/auth/session": () => new Response(null, { status: 204 }),
      "POST /api/v1/thing": () => new Response(null, { status: 204 }),
    });
    const queryClient = testQueryClient();
    const user = userEvent.setup();
    renderApp("/protocol", queryClient);
    await screen.findByRole("heading", { name: "Protokoll" });

    // A background refresh starts (as on window focus) and the server is slow to answer it.
    void queryClient.refetchQueries({ queryKey: SESSION_KEY });
    await waitFor(() => expect(late).not.toBeNull());

    await user.click(screen.getByRole("button", { name: "Abmelden" }));
    expect(await screen.findByLabelText("API-Token")).toBeInTheDocument();

    // Now the old answer arrives: it describes a session that no longer exists.
    late!(jsonResponse(SESSION));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.getByLabelText("API-Token")).toBeInTheDocument();
    expect(screen.queryByTestId("signed-in-user")).not.toBeInTheDocument();
    expect(queryClient.getQueryData(SESSION_KEY)).toBeNull();
    // Its CSRF token was not taken either.
    await apiFetch("/api/v1/thing", { method: "POST" });
    expect(calls.at(-1)!.headers.has(CSRF_HEADER)).toBe(false);
  });

  it("a 'not signed in' answer from before the sign-in does not end the fresh session", async () => {
    let late: ((response: Response) => void) | null = null;
    let reads = 0;
    const calls = stubFetch({
      "GET /api/v1/auth/session": () => (reads++ === 0 ? signedOut() : new Promise<Response>((resolve) => (late = resolve))),
      "POST /api/v1/auth/session": () => jsonResponse(SESSION, { status: 201 }),
      "GET /api/v1/info": () => jsonResponse(INFO),
      "POST /api/v1/thing": () => new Response(null, { status: 204 }),
    });
    const queryClient = testQueryClient();
    const user = userEvent.setup();
    renderApp("/sign-in", queryClient);
    const field = await screen.findByLabelText("API-Token");

    void queryClient.refetchQueries({ queryKey: SESSION_KEY });
    await waitFor(() => expect(late).not.toBeNull());

    await user.type(field, "bb_token");
    await user.click(screen.getByRole("button", { name: "Anmelden" }));
    await screen.findByTestId("signed-in-user");
    queryClient.setQueryData(["events"], ["mine"]);

    late!(signedOut());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.getByTestId("signed-in-user")).toHaveTextContent("Angemeldet als admin");
    expect(queryClient.getQueryData(SESSION_KEY)).toMatchObject({ user: "admin" });
    // Neither the CSRF token nor the new user's data were dropped by the stale answer.
    expect(queryClient.getQueryData(["events"])).toEqual(["mine"]);
    await apiFetch("/api/v1/thing", { method: "POST" });
    expect(calls.at(-1)!.headers.get(CSRF_HEADER)).toBe("csrf-1");
  });

  it("a late answer for another person does not drop the data of the one who signed in meanwhile", async () => {
    let late: ((response: Response) => void) | null = null;
    let reads = 0;
    stubFetch({
      "GET /api/v1/auth/session": () => (reads++ === 0 ? signedOut() : new Promise<Response>((resolve) => (late = resolve))),
      "POST /api/v1/auth/session": () => jsonResponse(SESSION, { status: 201 }),
      "GET /api/v1/info": () => jsonResponse(INFO),
    });
    const queryClient = testQueryClient();
    const user = userEvent.setup();
    renderApp("/sign-in", queryClient);
    const field = await screen.findByLabelText("API-Token");
    void queryClient.refetchQueries({ queryKey: SESSION_KEY });
    await waitFor(() => expect(late).not.toBeNull());
    await user.type(field, "bb_token");
    await user.click(screen.getByRole("button", { name: "Anmelden" }));
    await screen.findByTestId("signed-in-user");
    queryClient.setQueryData(["events"], ["mine"]);

    late!(jsonResponse({ ...SESSION, user: "Ada", identity_subject: "ada", csrf_token: "csrf-ada" }));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.getByTestId("signed-in-user")).toHaveTextContent("Angemeldet als admin");
    expect(queryClient.getQueryData(["events"])).toEqual(["mine"]);
  });
});

