import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setCsrfToken } from "../api/client";
import { BOOTSTRAP_HEADER } from "../app/router";
import { INFO, jsonResponse, problemResponse, renderApp, SESSION, stubFetch } from "../test-utils";

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  setCsrfToken(null);
  vi.unstubAllGlobals();
});

const signedOut = () => problemResponse(401, "not_authenticated", "Authentication required");
const CREATED = { id: "0", owner_user_id: "0", prefix: "bb_abcd", name: "First admin token", note: null, scope: "admin", expires_at: null, last_used_at: null, rate_limit_per_minute: 60, enabled: true, created_at: "2026-11-12T00:00:00Z", token: "bb_abcd_plaintext-shown-once" };

describe("first start", () => {
  it("creates the first admin token with the bootstrap key, shows it once and signs in with it", async () => {
    let signedIn = false;
    const calls = stubFetch({
      "GET /api/v1/auth/session": () => (signedIn ? jsonResponse(SESSION) : signedOut()),
      "POST /api/v1/admin/api-keys": () => jsonResponse(CREATED, { status: 201 }),
      "POST /api/v1/auth/session": () => {
        signedIn = true;
        return jsonResponse(SESSION, { status: 201 });
      },
      "GET /api/v1/info": () => jsonResponse(INFO),
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { router } = renderApp("/sign-in");

    await user.click(await screen.findByRole("link", { name: "Erstes Admin-Token anlegen" }));
    const keyField = await screen.findByLabelText("Bootstrap-Schlüssel");
    await user.type(keyField, "the-bootstrap-key");
    await user.click(screen.getByRole("button", { name: "Admin-Token anlegen" }));

    const shown = await screen.findByTestId("admin-token");
    expect(shown).toHaveTextContent("bb_abcd_plaintext-shown-once");
    expect(screen.getByRole("group", { name: "Admin-Token" })).toContainElement(shown);
    const create = calls.find((call) => call.path === "/api/v1/admin/api-keys")!;
    expect(create.headers.get(BOOTSTRAP_HEADER)).toBe("the-bootstrap-key");
    expect(create.body).toEqual({ name: "First admin token", scope: "admin" });
    // The bootstrap key is gone from the page once it was sent.
    expect(screen.queryByLabelText("Bootstrap-Schlüssel")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Token kopieren" }));
    expect(writeText).toHaveBeenCalledWith("bb_abcd_plaintext-shown-once");
    expect(await screen.findByText("Kopiert")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Weiter zur Oberfläche" }));
    expect(await screen.findByRole("heading", { name: "Übersicht" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
    expect(calls.find((call) => call.method === "POST" && call.path === "/api/v1/auth/session")!.body).toEqual({ token: "bb_abcd_plaintext-shown-once" });
    // Shown once: after the sign-in the token is nowhere in the page.
    expect(document.body.innerHTML).not.toContain("bb_abcd_plaintext-shown-once");
  });

  it("explains a rejected key, a closed bootstrap and other failures without leaving the form", async () => {
    const answers: (() => Response | Promise<Response>)[] = [
      () => problemResponse(401, "invalid_bootstrap_key", "Bootstrap key rejected"),
      () => problemResponse(403, "bootstrap_closed", "Bootstrap is closed"),
      () => problemResponse(429, "rate_limited", "Rate limit exceeded"),
      () => Promise.reject(new TypeError("Failed to fetch")),
      () => problemResponse(503, "database_unavailable", "Database unavailable"),
    ];
    stubFetch({ "GET /api/v1/auth/session": signedOut, "POST /api/v1/admin/api-keys": () => answers.shift()!() });
    const user = userEvent.setup();
    renderApp("/bootstrap");

    const field = await screen.findByLabelText("Bootstrap-Schlüssel");
    for (const expected of [
      "Der Bootstrap-Schlüssel wurde nicht akzeptiert.",
      "Es gibt bereits ein Admin-Token. Melde dich damit an.",
      "Zu viele Versuche. Warte eine Minute und versuche es erneut.",
      "Der Server ist nicht erreichbar.",
      "Das Token konnte nicht angelegt werden.",
    ]) {
      await user.clear(field);
      await user.type(field, "k");
      await user.click(screen.getByRole("button", { name: "Admin-Token anlegen" }));
      await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(expected));
    }
    expect(screen.queryByTestId("admin-token")).not.toBeInTheDocument();
  });

  it("keeps the token on screen when the sign-in with it fails, and names a failed copy", async () => {
    stubFetch({
      "GET /api/v1/auth/session": signedOut,
      "POST /api/v1/admin/api-keys": () => jsonResponse(CREATED, { status: 201 }),
      "POST /api/v1/auth/session": () => problemResponse(503, "database_unavailable", "Database unavailable"),
    });
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }, configurable: true });
    renderApp("/bootstrap");

    await user.type(await screen.findByLabelText("Bootstrap-Schlüssel"), "k");
    await user.click(screen.getByRole("button", { name: "Admin-Token anlegen" }));
    await screen.findByTestId("admin-token");

    await user.click(screen.getByRole("button", { name: "Token kopieren" }));
    expect(await screen.findByText("Kopieren fehlgeschlagen. Markiere das Token und kopiere es von Hand.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Weiter zur Oberfläche" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Die Anmeldung mit dem neuen Token ist fehlgeschlagen.");
    expect(screen.getByTestId("admin-token")).toHaveTextContent("bb_abcd_plaintext-shown-once");
  });

  it("leads back to the sign-in", async () => {
    stubFetch({ "GET /api/v1/auth/session": signedOut });
    const user = userEvent.setup();
    const { router } = renderApp("/bootstrap");
    await user.click(await screen.findByRole("link", { name: "Zurück zur Anmeldung" }));
    expect(await screen.findByLabelText("API-Token")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
  });

  it("warns before the page is left while the new token is on screen, and names the way back in", async () => {
    stubFetch({
      "GET /api/v1/auth/session": signedOut,
      "POST /api/v1/admin/api-keys": () => jsonResponse(CREATED, { status: 201 }),
      "POST /api/v1/auth/session": () => problemResponse(503, "database_unavailable", "Database unavailable"),
    });
    const leaving = () => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    const user = userEvent.setup();
    const view = renderApp("/bootstrap");

    await user.type(await screen.findByLabelText("Bootstrap-Schlüssel"), "k");
    expect(leaving()).toBe(false);
    await user.click(screen.getByRole("button", { name: "Admin-Token anlegen" }));
    await screen.findByTestId("admin-token");

    expect(leaving()).toBe(true);
    expect(screen.getByText(/bambubridge admin create-key/)).toBeInTheDocument();

    // A sign-in that failed leaves the token unused: still guarded.
    await user.click(screen.getByRole("button", { name: "Weiter zur Oberfläche" }));
    await screen.findByRole("alert");
    expect(leaving()).toBe(true);

    view.unmount();
    expect(leaving()).toBe(false);
  });

  it("stops warning once the token was used to sign in", async () => {
    let signedIn = false;
    stubFetch({
      "GET /api/v1/auth/session": () => (signedIn ? jsonResponse(SESSION) : signedOut()),
      "POST /api/v1/admin/api-keys": () => jsonResponse(CREATED, { status: 201 }),
      "POST /api/v1/auth/session": () => {
        signedIn = true;
        return jsonResponse(SESSION, { status: 201 });
      },
      "GET /api/v1/info": () => jsonResponse(INFO),
    });
    const user = userEvent.setup();
    renderApp("/bootstrap");
    await user.type(await screen.findByLabelText("Bootstrap-Schlüssel"), "k");
    await user.click(screen.getByRole("button", { name: "Admin-Token anlegen" }));
    await user.click(await screen.findByRole("button", { name: "Weiter zur Oberfläche" }));
    await screen.findByTestId("signed-in-user");
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("the bootstrap key is not offered to a password manager", async () => {
    stubFetch({ "GET /api/v1/auth/session": signedOut });
    renderApp("/bootstrap");
    expect(await screen.findByLabelText("Bootstrap-Schlüssel")).toHaveAttribute("autocomplete", "off");
  });

  async function tokenShown(sessionPost: () => Response = () => problemResponse(503, "database_unavailable", "Database unavailable")) {
    stubFetch({
      "GET /api/v1/auth/session": signedOut,
      "POST /api/v1/admin/api-keys": () => jsonResponse(CREATED, { status: 201 }),
      "POST /api/v1/auth/session": sessionPost,
    });
    const user = userEvent.setup();
    // Reached through the in-app link, so "Back" stays inside the app.
    const view = renderApp("/sign-in");
    await user.click(await screen.findByRole("link", { name: "Erstes Admin-Token anlegen" }));
    await user.type(await screen.findByLabelText("Bootstrap-Schlüssel"), "k");
    await user.click(screen.getByRole("button", { name: "Admin-Token anlegen" }));
    await screen.findByTestId("admin-token");
    return { user, ...view };
  }

  it("asks before Back or an in-app link leaves the unused token, and staying keeps it", async () => {
    const { user, router } = await tokenShown();

    // (Back is asked the same way by the browser history; the browser tests cover it. The
    // in-memory history of this test only asks for navigations.)
    void router.navigate({ to: "/sign-in", search: { redirect: undefined } });
    const question = await screen.findByRole("alertdialog");
    expect(question).toHaveTextContent("Das Token wird danach nicht mehr angezeigt.");
    expect(screen.getByTestId("admin-token")).toHaveTextContent("bb_abcd_plaintext-shown-once");
    await waitFor(() => expect(screen.getByRole("button", { name: "Hier bleiben" })).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Hier bleiben" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/bootstrap");
    expect(screen.getByTestId("admin-token")).toHaveTextContent("bb_abcd_plaintext-shown-once");

    void router.navigate({ to: "/sign-in", search: { redirect: undefined } });
    await screen.findByRole("alertdialog");
    await user.click(screen.getByRole("button", { name: "Trotzdem verlassen" }));
    expect(await screen.findByLabelText("API-Token")).toBeInTheDocument();
    expect(screen.queryByTestId("admin-token")).not.toBeInTheDocument();
  });

  it("does not ask before the token exists, nor when it was used to sign in", async () => {
    stubFetch({ "GET /api/v1/auth/session": signedOut });
    const user = userEvent.setup();
    renderApp("/bootstrap");
    await user.click(await screen.findByRole("link", { name: "Zurück zur Anmeldung" }));
    expect(await screen.findByLabelText("API-Token")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("after a failed sign-in with the new token the focus is back on the continue button", async () => {
    const { user } = await tokenShown();
    const proceed = screen.getByRole("button", { name: "Weiter zur Oberfläche" });
    await user.click(proceed);
    await screen.findByRole("alert");
    await waitFor(() => expect(proceed).toHaveFocus());
  });

  it("keeps the typed bootstrap key unless the server refused it", async () => {
    const answers: (() => Response | Promise<Response>)[] = [
      () => Promise.reject(new TypeError("Failed to fetch")),
      () => problemResponse(429, "rate_limited", "Too many attempts"),
      () => problemResponse(503, "database_unavailable", "Database unavailable"),
      () => problemResponse(401, "invalid_bootstrap_key", "Invalid bootstrap key"),
    ];
    stubFetch({ "GET /api/v1/auth/session": signedOut, "POST /api/v1/admin/api-keys": () => answers.shift()!() });
    const user = userEvent.setup();
    renderApp("/bootstrap");
    const field = await screen.findByLabelText("Bootstrap-Schlüssel");
    await user.type(field, "typed-once");
    for (const expected of ["Der Server ist nicht erreichbar.", "Zu viele Versuche.", "Das Token konnte nicht angelegt werden."]) {
      await user.click(screen.getByRole("button", { name: "Admin-Token anlegen" }));
      await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(expected));
      expect(field).toHaveValue("typed-once");
    }
    await user.click(screen.getByRole("button", { name: "Admin-Token anlegen" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Der Bootstrap-Schlüssel wurde nicht akzeptiert."));
    expect(field).toHaveValue("");
    await waitFor(() => expect(field).toHaveFocus());
  });

  it("shows the error state when the server's answer holds no token", async () => {
    stubFetch({ "GET /api/v1/auth/session": signedOut, "POST /api/v1/admin/api-keys": () => jsonResponse({ ...CREATED, token: "" }, { status: 201 }) });
    const user = userEvent.setup();
    renderApp("/bootstrap");
    await user.type(await screen.findByLabelText("Bootstrap-Schlüssel"), "k");
    await user.click(screen.getByRole("button", { name: "Admin-Token anlegen" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Das Token konnte nicht angelegt werden.");
    expect(screen.queryByTestId("admin-token")).not.toBeInTheDocument();
  });

  async function creating() {
    let answer!: (response: Response) => void;
    stubFetch({
      "GET /api/v1/auth/session": signedOut,
      "POST /api/v1/admin/api-keys": () => new Promise<Response>((resolve) => (answer = resolve)),
    });
    const user = userEvent.setup();
    const view = renderApp("/sign-in");
    await user.click(await screen.findByRole("link", { name: "Erstes Admin-Token anlegen" }));
    const field = await screen.findByLabelText<HTMLInputElement>("Bootstrap-Schlüssel");
    await user.type(field, "the-key");
    await user.click(screen.getByRole("button", { name: "Admin-Token anlegen" }));
    return { user, field, answer: (response: Response) => answer(response), ...view };
  }

  const leaving = () => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  };

  it("while the token is being created, leaving asks first and the way back is not offered", async () => {
    const { user, router, answer } = await creating();

    // The server may already have made the token: a closed tab or a reload would lose it.
    expect(leaving()).toBe(true);
    const back = screen.getByRole("link", { name: "Zurück zur Anmeldung" });
    expect(back).toHaveAttribute("aria-disabled", "true");
    await user.click(back);
    expect(router.state.location.pathname).toBe("/bootstrap");

    void router.navigate({ to: "/sign-in", search: { redirect: undefined } });
    const question = await screen.findByRole("alertdialog");
    expect(question).toHaveTextContent("Das Token wird danach nicht mehr angezeigt.");
    expect(router.state.location.pathname).toBe("/bootstrap");

    // The answer arrives while the question is open: the token is shown, the question stays.
    answer(jsonResponse(CREATED, { status: 201 }));
    expect(await screen.findByTestId("admin-token")).toHaveTextContent("bb_abcd_plaintext-shown-once");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hier bleiben" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("admin-token")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Weiter zur Oberfläche" })).toHaveFocus());
  });

  it("stops guarding when the creation failed: nothing was made, so nothing can be lost", async () => {
    const { router, answer } = await creating();
    void router.navigate({ to: "/sign-in", search: { redirect: undefined } });
    await screen.findByRole("alertdialog");

    answer(problemResponse(401, "invalid_bootstrap_key", "Invalid bootstrap key"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Der Bootstrap-Schlüssel wurde nicht akzeptiert.");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(leaving()).toBe(false);
    expect(screen.getByRole("link", { name: "Zurück zur Anmeldung" })).not.toHaveAttribute("aria-disabled", "true");
  });

  it("does not keep the bootstrap key in the field once the token exists or the key was refused", async () => {
    const first = await creating();
    first.answer(jsonResponse(CREATED, { status: 201 }));
    await screen.findByTestId("admin-token");
    expect(first.field.value).toBe("");
    expect(first.field.getAttribute("value") ?? "").toBe("");
    first.unmount();

    const second = await creating();
    second.answer(problemResponse(401, "invalid_bootstrap_key", "Invalid bootstrap key"));
    await screen.findByRole("alert");
    expect(second.field.value).toBe("");
    expect(second.field.getAttribute("value") ?? "").toBe("");
  });
});
