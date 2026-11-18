import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, problemResponse, renderApp, SIGNED_IN, stubFetch } from "../../test-utils";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

type Handler = (init: RequestInit) => Response | Promise<Response>;

const base = { undecryptable: false, min: null, max: null, choices: null } as const;
const SETTINGS = [
  { ...base, key: "retention.events_days", type: "int", section: "retention", value: 90, default: 90, set: false, min: 1, max: 3650 },
  { ...base, key: "retention.communication_days", type: "int", section: "retention", value: 30, default: 30, set: true, min: 1, max: 3650 },
  { ...base, key: "sso.user_header", type: "choice", section: "sso", value: "Remote-User", default: "Remote-User", set: false, choices: ["Remote-User", "X-Forwarded-User"] },
  { ...base, key: "sso.trust_header", type: "str", section: "sso", value: "X-Pangolin-Token", default: "X-Pangolin-Token", set: false },
  { ...base, key: "sso.trust_token", type: "secret", section: "sso", value: null, default: null, set: true },
  { ...base, key: "auth.sign_in_limit_per_minute", type: "int", section: "auth", value: 10, default: 10, set: false, min: 1, max: 600 },
  { ...base, key: "auth.identity_providers", type: "choices", section: "auth", value: ["pangolin_header"], default: ["pangolin_header"], set: false, choices: ["pangolin_header"] },
  { ...base, key: "events.dedup_window_seconds", type: "int", section: "events", value: 600, default: 600, set: false, min: 0, max: 86400 },
] as const;

const KEY = {
  id: "88888888-8888-4888-8888-888888888888",
  owner_user_id: "99999999-9999-4999-8999-999999999999",
  prefix: "bb_pat_abcd",
  name: "CI reader",
  note: "for the pipeline",
  scope: "read",
  expires_at: null,
  last_used_at: null,
  rate_limit_per_minute: 60,
  enabled: true,
  created_at: "2026-11-17T08:00:00Z",
} as const;

function answers(extra: Record<string, Handler> = {}) {
  return stubFetch({
    ...SIGNED_IN,
    "GET /api/v1/settings": () => jsonResponse(SETTINGS),
    "GET /api/v1/admin/api-keys": () => jsonResponse([KEY]),
    ...extra,
  });
}

describe("settings index", () => {
  it("lists every section and the device page", async () => {
    answers();
    renderApp("/settings");
    const nav = await screen.findByRole("navigation", { name: "Einstellungsseiten" });
    const hrefs = within(nav).getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(hrefs).toEqual(["/settings/general", "/settings/access", "/settings/sso", "/settings/retention", "/settings/system", "/device"]);
  });
});

describe("retention", () => {
  it("saves only what was changed and says the change needs no restart", async () => {
    const user = userEvent.setup();
    const calls = answers({ "PUT /api/v1/settings": () => new Response(null, { status: 204 }) });
    renderApp("/settings/retention");
    const days = await screen.findByRole("spinbutton", { name: "Ereignisse aufbewahren (Tage)" });
    expect(days).toHaveValue(90);
    expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();
    await user.clear(days);
    await user.type(days, "14");
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    expect(await screen.findByRole("status")).toHaveTextContent("ohne Neustart");
    expect(calls.find((call) => call.method === "PUT")!.body).toEqual({ values: { "retention.events_days": 14 } });
  });

  it("an emptied number field cannot be saved: the typed value is not sent behind its back", async () => {
    const user = userEvent.setup();
    const calls = answers({ "PUT /api/v1/settings": () => new Response(null, { status: 204 }) });
    renderApp("/settings/retention");
    const days = await screen.findByRole("spinbutton", { name: "Ereignisse aufbewahren (Tage)" });
    await user.clear(days);
    await user.type(days, "14");
    expect(screen.getByRole("button", { name: "Speichern" })).toBeEnabled();
    await user.clear(days);
    expect(screen.getByText("Bitte eine ganze Zahl eingeben.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();
    await user.type(days, "{Enter}");
    expect(calls.some((call) => call.method === "PUT")).toBe(false);

    await user.type(days, "21");
    expect(screen.queryByText("Bitte eine ganze Zahl eingeben.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    expect(calls.find((call) => call.method === "PUT")!.body).toEqual({ values: { "retention.events_days": 21 } });
  });

  it("after a save the number field shows the value the server now has, not the old one", async () => {
    const user = userEvent.setup();
    let stored = 90;
    answers({
      // The refresh answers a little later than the save, as a real one does.
      "GET /api/v1/settings": async () => {
        await new Promise((resolve) => setTimeout(resolve, 60));
        return jsonResponse(SETTINGS.map((setting) => (setting.key === "retention.events_days" ? { ...setting, value: stored, set: true } : setting)));
      },
      "PUT /api/v1/settings": () => {
        stored = 14;
        return new Response(null, { status: 204 });
      },
    });
    renderApp("/settings/retention");
    const days = await screen.findByRole("spinbutton", { name: "Ereignisse aufbewahren (Tage)" });
    await user.clear(days);
    await user.type(days, "14");
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    expect(await screen.findByRole("status")).toHaveTextContent("ohne Neustart");
    expect(screen.getByRole("spinbutton", { name: "Ereignisse aufbewahren (Tage)" })).toHaveValue(14);
  });

  it("a value outside the bounds is held back by the browser before anything is sent", async () => {
    const user = userEvent.setup();
    const calls = answers({ "PUT /api/v1/settings": () => new Response(null, { status: 204 }) });
    renderApp("/settings/retention");
    const days = await screen.findByRole("spinbutton", { name: "Ereignisse aufbewahren (Tage)" });
    await user.clear(days);
    await user.type(days, "99999");
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    expect(calls.some((call) => call.method === "PUT")).toBe(false);
  });

  it("resets a stored value to the default with null", async () => {
    const user = userEvent.setup();
    const calls = answers({ "PUT /api/v1/settings": () => new Response(null, { status: 204 }) });
    renderApp("/settings/retention");
    await user.click(await screen.findByRole("button", { name: "Kommunikationsprotokoll aufbewahren (Tage): auf Standard zurücksetzen" }));
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    expect(calls.find((call) => call.method === "PUT")!.body).toEqual({ values: { "retention.communication_days": null } });
  });

  it("discarding the changes puts the stored values back", async () => {
    const user = userEvent.setup();
    answers();
    renderApp("/settings/retention");
    const days = await screen.findByRole("spinbutton", { name: "Ereignisse aufbewahren (Tage)" });
    await user.clear(days);
    await user.type(days, "5");
    await user.click(screen.getByRole("button", { name: "Änderungen verwerfen" }));
    expect(screen.getByRole("spinbutton", { name: "Ereignisse aufbewahren (Tage)" })).toHaveValue(90);
  });
});

describe("single sign-on", () => {
  it("changes the header; the trust token is write-only and never shown", async () => {
    const user = userEvent.setup();
    const calls = answers({ "PUT /api/v1/settings": () => new Response(null, { status: 204 }) });
    renderApp("/settings/sso");
    await user.selectOptions(await screen.findByRole("combobox", { name: "Kopfzeile mit dem Benutzernamen" }), "X-Forwarded-User");
    expect(screen.getByTestId("secret-state-sso.trust_token")).toHaveTextContent("gesetzt");
    expect(screen.getByLabelText("Vertrauens-Token (leer schaltet SSO aus)")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const body = calls.find((call) => call.method === "PUT")!.body as { values: Record<string, unknown> };
    expect(body).toEqual({ values: { "sso.user_header": "X-Forwarded-User" } });
  });

  it("an invalid value is refused by the server and the reason is shown", async () => {
    const user = userEvent.setup();
    answers({ "PUT /api/v1/settings": () => problemResponse(422, "invalid_setting_value", "Invalid setting value") });
    renderApp("/settings/sso");
    const header = await screen.findByRole("textbox", { name: "Kopfzeile mit dem Vertrauens-Token" });
    await user.clear(header);
    await user.type(header, "not a header");
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid setting value");
  });

  it("sets and removes the trust token", async () => {
    const user = userEvent.setup();
    const calls = answers({ "PUT /api/v1/settings": () => new Response(null, { status: 204 }) });
    renderApp("/settings/sso");
    await user.type(await screen.findByLabelText("Vertrauens-Token (leer schaltet SSO aus)"), "t".repeat(32));
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(calls.filter((call) => call.method === "PUT")).toHaveLength(1));
    expect(calls.find((call) => call.method === "PUT")!.body).toEqual({ values: { "sso.trust_token": "t".repeat(32) } });

    await user.click(await screen.findByRole("button", { name: /Vertrauens-Token \(leer schaltet SSO aus\): entfernen/ }));
    expect(screen.getByTestId("secret-state-sso.trust_token")).toHaveTextContent("wird entfernt");
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(calls.filter((call) => call.method === "PUT")).toHaveLength(2));
    expect(calls.filter((call) => call.method === "PUT")[1]!.body).toEqual({ values: { "sso.trust_token": null } });
  });

  it("a secret that cannot be decrypted asks for a new one", async () => {
    answers({ "GET /api/v1/settings": () => jsonResponse(SETTINGS.map((s) => (s.key === "sso.trust_token" ? { ...s, set: true, undecryptable: true } : s))) });
    renderApp("/settings/sso");
    expect(await screen.findByTestId("secret-state-sso.trust_token")).toHaveTextContent("neu eingeben nötig");
  });
});

describe("access", () => {
  it("resetting a choices field previews the default, not an empty selection", async () => {
    const user = userEvent.setup();
    const calls = answers({
      "GET /api/v1/settings": () => jsonResponse(SETTINGS.map((s) => (s.key === "auth.identity_providers" ? { ...s, set: true } : s))),
      "PUT /api/v1/settings": () => new Response(null, { status: 204 }),
    });
    renderApp("/settings/access");
    const provider = await screen.findByRole("checkbox", { name: "pangolin_header" });
    expect(provider).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Anmeldedienste (in dieser Reihenfolge gefragt): auf Standard zurücksetzen" }));
    // What is previewed is what the save will give: the default stays selected.
    expect(screen.getByRole("checkbox", { name: "pangolin_header" })).toBeChecked();
    expect(screen.queryByText("Ohne Auswahl ist die Anmeldung über Kopfzeilen aus.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    expect(calls.find((call) => call.method === "PUT")!.body).toEqual({ values: { "auth.identity_providers": null } });
  });

  it("shows the plaintext of a new token once, and the list afterwards only its start", async () => {
    const user = userEvent.setup();
    const secret = "bb_pat_" + "Z".repeat(40);
    let keys: unknown[] = [KEY];
    const calls = answers({
      "GET /api/v1/admin/api-keys": () => jsonResponse(keys),
      "POST /api/v1/admin/api-keys": () => {
        keys = [KEY, { ...KEY, id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "New one", prefix: "bb_pat_wxyz", token: undefined }];
        return jsonResponse({ ...(keys[1] as object), token: secret }, { status: 201 });
      },
    });
    renderApp("/settings/access");
    await user.click(await screen.findByRole("button", { name: "Token anlegen" }));
    const sheet = await screen.findByRole("dialog");
    await user.type(within(sheet).getByRole("textbox", { name: "Name" }), "New one");
    await user.selectOptions(within(sheet).getByLabelText("Berechtigung"), "operate");
    await user.click(within(sheet).getByRole("button", { name: "Anlegen" }));

    const shown = await screen.findByTestId("new-token");
    expect(shown).toHaveTextContent(secret);
    expect(calls.find((call) => call.method === "POST")!.body).toEqual({ name: "New one", scope: "operate" });

    await user.click(screen.getByRole("button", { name: "Fertig" }));
    await waitFor(() => expect(screen.queryByTestId("new-token")).not.toBeInTheDocument());
    expect(document.body.textContent).not.toContain(secret);
    expect(await screen.findByRole("article", { name: "New one" })).toHaveTextContent("bb_pat_wxyz…");
  });

  it("revokes a token only after asking", async () => {
    const user = userEvent.setup();
    let keys = [KEY];
    const calls = answers({
      "GET /api/v1/admin/api-keys": () => jsonResponse(keys),
      [`DELETE /api/v1/admin/api-keys/${KEY.id}`]: () => {
        keys = [];
        return new Response(null, { status: 204 });
      },
    });
    renderApp("/settings/access");
    await user.click(await screen.findByRole("button", { name: "Token „CI reader“ entziehen" }));
    const dialog = await screen.findByRole("dialog");
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    await user.click(within(dialog).getByRole("button", { name: "Endgültig entziehen" }));
    expect(await screen.findByText("Es gibt noch kein Token.")).toBeInTheDocument();
  });

  it("a failed copy is said, not swallowed", async () => {
    const user = userEvent.setup();
    answers({ "POST /api/v1/admin/api-keys": () => jsonResponse({ ...KEY, token: "bb_pat_x" }, { status: 201 }) });
    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }, configurable: true });
    renderApp("/settings/access");
    await user.click(await screen.findByRole("button", { name: "Token anlegen" }));
    await user.type(within(await screen.findByRole("dialog")).getByRole("textbox", { name: "Name" }), "n");
    await user.click(screen.getByRole("button", { name: "Anlegen" }));
    await user.click(await screen.findByRole("button", { name: "In die Zwischenablage kopieren" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Kopieren ging nicht");
  });

  it("a missing clipboard (plain http) is said too, not thrown", async () => {
    const user = userEvent.setup();
    answers({ "POST /api/v1/admin/api-keys": () => jsonResponse({ ...KEY, token: "bb_pat_x" }, { status: 201 }) });
    // `writeText` is not even there: calling it throws before any promise exists.
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    renderApp("/settings/access");
    await user.click(await screen.findByRole("button", { name: "Token anlegen" }));
    await user.type(within(await screen.findByRole("dialog")).getByRole("textbox", { name: "Name" }), "n");
    await user.click(screen.getByRole("button", { name: "Anlegen" }));
    await user.click(await screen.findByRole("button", { name: "In die Zwischenablage kopieren" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Kopieren ging nicht");
  });

  it("the sign-in limit sits on this page", async () => {
    answers();
    renderApp("/settings/access");
    expect(await screen.findByRole("spinbutton", { name: "Anmeldeversuche pro Minute" })).toHaveValue(10);
    expect(screen.getByRole("checkbox", { name: "pangolin_header" })).toBeChecked();
  });
});

describe("system and general", () => {
  it("system shows version, build and the readiness of the parts", async () => {
    answers();
    renderApp("/settings/system");
    expect(await screen.findByTestId("server-version")).toHaveTextContent("0.2.0");
    expect(await screen.findAllByText("In Ordnung")).toHaveLength(2);
    expect(screen.getByRole("link", { name: /Beschreibung der Schnittstelle/ })).toHaveAttribute("href", "/docs");
  });

  it("system names the part that is down, taken from the 503 body", async () => {
    answers({ "GET /readiness": () => jsonResponse({ database: "ok", listener: "unavailable" }, { status: 503 }) });
    renderApp("/settings/system");
    expect(await screen.findByTestId("server-version")).toHaveTextContent("0.2.0");
    const state = await screen.findByRole("region", { name: "Zustand" });
    expect(await within(state).findByText("In Ordnung")).toBeInTheDocument();
    expect(within(state).getByText("Nicht erreichbar")).toBeInTheDocument();
    expect(within(state).queryByText("Unbekannt")).not.toBeInTheDocument();
  });

  it("system says 'unknown' only when the 503 has no readable body", async () => {
    answers({ "GET /readiness": () => problemResponse(503, "database_unavailable", "x") });
    renderApp("/settings/system");
    expect(await screen.findAllByText("Unbekannt")).toHaveLength(2);
  });

  it("general holds the deduplication window", async () => {
    answers();
    renderApp("/settings/general");
    expect(await screen.findByRole("spinbutton", { name: "Zeitfenster gegen doppelte Ereignisse (Sekunden)" })).toHaveValue(600);
  });

  it("an unknown section says so and leads back", async () => {
    answers();
    renderApp("/settings/nope");
    expect(await screen.findByRole("heading", { name: "Einstellung nicht gefunden" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Zurück zu den Einstellungen" })).toHaveAttribute("href", "/settings");
  });
});
