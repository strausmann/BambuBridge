import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { DEMO_INSTANCE, DEMO_TYPE, jsonResponse, problemResponse, renderApp, SIGNED_IN, stubFetch } from "../../test-utils";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

type Handler = (init: RequestInit) => Response | Promise<Response>;

function answers(extra: Record<string, Handler> = {}) {
  return stubFetch({
    ...SIGNED_IN,
    "GET /api/v1/providers": () => jsonResponse([DEMO_INSTANCE]),
    "GET /api/v1/provider-types": () => jsonResponse([DEMO_TYPE]),
    ...extra,
  });
}

describe("providers page", () => {
  it("shows every type with its event types and actions, schemas included", async () => {
    answers();
    renderApp("/providers");
    const type = await screen.findByRole("article", { name: "demo (integration)" });
    expect(within(type).getByText("integration.demo.tick")).toBeInTheDocument();
    expect(within(type).getByText("Version 1")).toBeInTheDocument();
    expect(within(type).getByText("emit_now")).toBeInTheDocument();
    // The schemas are one disclosure away and hold the real schema.
    expect(within(type).getByLabelText("Schema der Einstellungen", { selector: "pre" })).toHaveTextContent('"interval_seconds"');
    expect(within(type).getByLabelText("Schema der Nutzdaten von integration.demo.tick", { selector: "pre" })).toHaveTextContent('"sequence"');
    expect(within(type).getByLabelText("Schema der Parameter von emit_now", { selector: "pre" })).toHaveTextContent('"properties"');
  });

  it("lists the instances with their status and says when there is none", async () => {
    answers();
    const first = renderApp("/providers");
    const card = await screen.findByRole("article", { name: "Workshop demo" });
    expect(within(card).getByText("Verbunden")).toBeInTheDocument();
    first.unmount();
    answers({ "GET /api/v1/providers": () => jsonResponse([]) });
    renderApp("/providers");
    expect(await screen.findByText(/Es gibt noch keine Instanz/)).toBeInTheDocument();
  });

  it("makes a new instance: type picked, secret typed, tested with the unsaved values, saved", async () => {
    const user = userEvent.setup();
    const calls = answers({
      "POST /api/v1/provider-types/integration/demo/test": () => jsonResponse({ ok: true, message: "the token is set", duration_ms: 3 }),
      "POST /api/v1/providers": () => jsonResponse({ ...DEMO_INSTANCE, name: "Fresh" }, { status: 201 }),
    });
    renderApp("/providers");
    await user.click(await screen.findByRole("button", { name: "Instanz hinzufügen" }));

    const sheet = await screen.findByRole("dialog");
    await user.click(within(sheet).getByRole("combobox", { name: "Typ" }));
    await user.click(await screen.findByRole("option", { name: "demo (integration)" }));

    await user.type(await within(sheet).findByRole("textbox", { name: "Name" }), "Fresh");
    // Defaults come from the schema; the secret starts empty.
    expect(within(sheet).getByRole("textbox", { name: "Label" })).toHaveValue("demo");
    expect(within(sheet).getByRole("spinbutton", { name: /Interval/ })).toHaveValue(30);
    await user.type(within(sheet).getByLabelText(/^Token/, { selector: "input" }), "s3cret-value");

    await user.click(within(sheet).getByRole("button", { name: "Verbindung testen" }));
    expect(await within(sheet).findByTestId("probe-result")).toHaveTextContent("Verbindung in Ordnung");
    const test = calls.find((call) => call.path.endsWith("/test"))!;
    expect(test.body).toEqual({ config: { interval_seconds: 30, label: "demo", token: "s3cret-value" } });

    await user.click(within(sheet).getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST" && call.path === "/api/v1/providers")).toBe(true));
    expect(calls.find((call) => call.method === "POST" && call.path === "/api/v1/providers")!.body).toEqual({
      kind: "integration",
      type_name: "demo",
      name: "Fresh",
      enabled: true,
      config: { interval_seconds: 30, label: "demo", token: "s3cret-value" },
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("changes an instance: the stored secret stays out of the form and is not sent unless typed", async () => {
    const user = userEvent.setup();
    const calls = answers({ [`PATCH /api/v1/providers/${DEMO_INSTANCE.id}`]: () => jsonResponse({ ...DEMO_INSTANCE, config: { interval_seconds: 5, label: "demo" } }) });
    renderApp("/providers");
    await user.click(await within(await screen.findByRole("article", { name: "Workshop demo" })).findByRole("button", { name: "Bearbeiten" }));
    const sheet = await screen.findByRole("dialog");

    expect(within(sheet).getByLabelText(/^Token/, { selector: "input" })).toHaveValue("");
    expect(within(sheet).getByTestId("secret-state-token")).toHaveTextContent("gesetzt");
    const interval = within(sheet).getByRole("spinbutton", { name: /Interval/ });
    await user.clear(interval);
    await user.type(interval, "5");
    await user.click(within(sheet).getByRole("button", { name: "Speichern" }));

    await waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    const patch = calls.find((call) => call.method === "PATCH")!;
    expect(patch.body).toEqual({ name: "Workshop demo", enabled: true, config: { interval_seconds: 5, label: "demo" } });
    expect(JSON.stringify(patch.body)).not.toContain("token");
  });

  it("removes a stored secret on request: the change sends null for it", async () => {
    const user = userEvent.setup();
    const calls = answers({ [`PATCH /api/v1/providers/${DEMO_INSTANCE.id}`]: () => jsonResponse({ ...DEMO_INSTANCE, secrets: { token: { set: false } } }) });
    renderApp("/providers");
    await user.click(await within(await screen.findByRole("article", { name: "Workshop demo" })).findByRole("button", { name: "Bearbeiten" }));
    const sheet = await screen.findByRole("dialog");
    await user.click(within(sheet).getByRole("button", { name: "Token: entfernen" }));
    await user.click(within(sheet).getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(calls.find((call) => call.method === "PATCH")!.body).toEqual({ name: "Workshop demo", enabled: true, config: { interval_seconds: 30, label: "demo", token: null } });
  });

  it("an invalid number blocks saving and testing, and the message says why", async () => {
    const user = userEvent.setup();
    const calls = answers();
    renderApp("/providers");
    await user.click(await within(await screen.findByRole("article", { name: "Workshop demo" })).findByRole("button", { name: "Bearbeiten" }));
    const sheet = await screen.findByRole("dialog");
    const interval = within(sheet).getByRole("spinbutton", { name: /Interval/ });
    await user.clear(interval);
    await user.type(interval, "2.5");
    expect(within(sheet).getByText("Bitte eine ganze Zahl eingeben.")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Speichern" })).toBeDisabled();
    expect(within(sheet).getByRole("button", { name: "Verbindung testen" })).toBeDisabled();
    expect(calls.some((call) => call.method === "PATCH" || call.path.endsWith("/test"))).toBe(false);
    await user.clear(interval);
    await user.type(interval, "3");
    expect(within(sheet).getByRole("button", { name: "Speichern" })).toBeEnabled();
  });

  it("names a taken name and an unreadable stored secret, and asks for the secret again", async () => {
    const user = userEvent.setup();
    answers({
      [`PATCH /api/v1/providers/${DEMO_INSTANCE.id}`]: () => problemResponse(409, "provider_name_taken", "Name taken"),
      [`POST /api/v1/providers/${DEMO_INSTANCE.id}/test`]: () => problemResponse(409, "secret_undecryptable", "Stored secret cannot be decrypted"),
    });
    renderApp("/providers");
    await user.click(await within(await screen.findByRole("article", { name: "Workshop demo" })).findByRole("button", { name: "Bearbeiten" }));
    const sheet = await screen.findByRole("dialog");

    await user.click(within(sheet).getByRole("button", { name: "Speichern" }));
    expect(await within(sheet).findByRole("alert")).toHaveTextContent("Dieser Name ist schon vergeben.");

    await user.click(within(sheet).getByRole("button", { name: "Verbindung testen" }));
    await waitFor(() => expect(within(sheet).getByTestId("secret-state-token")).toHaveTextContent("neu eingeben nötig"));
    expect(within(sheet).getByRole("alert")).toHaveTextContent("Gib es neu ein.");
  });

  it("tests a stored instance from its card", async () => {
    const user = userEvent.setup();
    const calls = answers({ [`POST /api/v1/providers/${DEMO_INSTANCE.id}/test`]: () => jsonResponse({ ok: false, message: "the token is empty", duration_ms: 1 }) });
    renderApp("/providers");
    const card = await screen.findByRole("article", { name: "Workshop demo" });
    await user.click(within(card).getByRole("button", { name: "Verbindung testen" }));
    expect(await within(card).findByText("Verbindung fehlgeschlagen")).toBeInTheDocument();
    expect(within(card).getByText("the token is empty")).toBeInTheDocument();
    expect(calls.find((call) => call.path.endsWith("/test"))!.body).toEqual({ config: {} });
  });

  it("runs an action and shows its result", async () => {
    const user = userEvent.setup();
    const calls = answers({ [`POST /api/v1/providers/${DEMO_INSTANCE.id}/actions/emit_now`]: () => jsonResponse({ result: { sequence: 42 } }) });
    renderApp("/providers");
    await user.click(await screen.findByRole("button", { name: "Aktion „emit_now“" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Ausführen" }));
    expect(await within(dialog).findByTestId("action-result")).toHaveTextContent('"sequence": 42');
    expect(calls.find((call) => call.path.endsWith("/actions/emit_now"))!.body).toEqual({ params: {} });
  });

  it("an action needs a running instance: the button is off while the instance is deactivated", async () => {
    answers({ "GET /api/v1/providers": () => jsonResponse([{ ...DEMO_INSTANCE, enabled: false }]) });
    renderApp("/providers");
    expect(await screen.findByRole("button", { name: "Aktion „emit_now“" })).toBeDisabled();
    expect(screen.getByText("Deaktiviert", { selector: "span span" })).toBeInTheDocument();
  });

  it("deletes an instance only after asking", async () => {
    const user = userEvent.setup();
    let gone = false;
    const calls = answers({
      "GET /api/v1/providers": () => jsonResponse(gone ? [] : [DEMO_INSTANCE]),
      [`DELETE /api/v1/providers/${DEMO_INSTANCE.id}`]: () => {
        gone = true;
        return new Response(null, { status: 204 });
      },
    });
    renderApp("/providers");
    await user.click(await within(await screen.findByRole("article", { name: "Workshop demo" })).findByRole("button", { name: "Löschen" }));
    const dialog = await screen.findByRole("dialog");
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    await user.click(within(dialog).getByRole("button", { name: "Endgültig löschen" }));
    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
    expect(await screen.findByText(/Es gibt noch keine Instanz/)).toBeInTheDocument();
  });

  it("switches an instance off and on", async () => {
    const user = userEvent.setup();
    const calls = answers({ [`PATCH /api/v1/providers/${DEMO_INSTANCE.id}`]: () => jsonResponse({ ...DEMO_INSTANCE, enabled: false }) });
    renderApp("/providers");
    await user.click(await within(await screen.findByRole("article", { name: "Workshop demo" })).findByRole("button", { name: "Deaktivieren" }));
    await waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(calls.find((call) => call.method === "PATCH")!.body).toEqual({ enabled: false });
  });

  it("a failed read says so and offers another try", async () => {
    answers({ "GET /api/v1/providers": () => problemResponse(500, "boom", "x") });
    renderApp("/providers");
    const card = await screen.findByRole("region", { name: "Instanzen" });
    expect(await within(card).findByRole("alert")).toHaveTextContent("Etwas ist schiefgegangen.");
    expect(within(card).getByRole("button", { name: "Erneut versuchen" })).toBeInTheDocument();
  });

  it("a long unbroken name does not widen the page", async () => {
    const long = "x".repeat(300);
    answers({ "GET /api/v1/providers": () => jsonResponse([{ ...DEMO_INSTANCE, name: long }]) });
    renderApp("/providers");
    const heading = await screen.findByRole("heading", { name: long });
    expect(heading.className).toContain("break-words");
  });
});
