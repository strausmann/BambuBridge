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
      await user.type(field, "k");
      await user.click(screen.getByRole("button", { name: "Admin-Token anlegen" }));
      await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(expected));
      expect(field).toHaveValue("");
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
});
