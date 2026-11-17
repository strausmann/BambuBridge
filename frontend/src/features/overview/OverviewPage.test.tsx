import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ApiError } from "../../api/client";
import { DEMO_INSTANCE, EVENT, jsonResponse, problemResponse, renderApp, SIGNED_IN, stubFetch } from "../../test-utils";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

const READY = { database: "ok", listener: "ok" };
const events = (n: number) => ({ items: Array.from({ length: n }, (_, i) => ({ ...EVENT, id: `00000000-0000-4000-8000-${String(i).padStart(12, "0")}` })), next_cursor: null });

function answers(extra: Record<string, () => Response | Promise<Response>> = {}) {
  return stubFetch({
    ...SIGNED_IN,
    "GET /readiness": () => jsonResponse(READY),
    "GET /api/v1/providers": () => jsonResponse([DEMO_INSTANCE]),
    "GET /api/v1/events?limit=10": () => jsonResponse(events(3)),
    ...extra,
  });
}

describe("overview page", () => {
  it("shows the system status from /readiness", async () => {
    answers();
    renderApp("/");
    const card = await screen.findByRole("region", { name: "Systemstatus" });
    expect(await within(card).findByText("Bereit")).toBeInTheDocument();
    expect(within(card).getAllByText("In Ordnung")).toHaveLength(2);
  });

  it("on a 503 it shows which part is down, taken from the body of the answer", async () => {
    answers({ "GET /readiness": () => jsonResponse({ database: "unavailable", listener: "ok" }, { status: 503 }) });
    renderApp("/");
    const card = await screen.findByRole("region", { name: "Systemstatus" });
    expect(await within(card).findByText("Nicht bereit")).toBeInTheDocument();
    expect(within(card).getByText("Nicht erreichbar")).toBeInTheDocument();
    expect(within(card).getByText("In Ordnung")).toBeInTheDocument();
    expect(within(card).queryByText(/meldet sich nicht bereit/)).not.toBeInTheDocument();
  });

  it("on a 503 without a readable body it says so and sends to the system page", async () => {
    answers({ "GET /readiness": () => problemResponse(503, "database_unavailable", "Database unavailable") });
    renderApp("/");
    const card = await screen.findByRole("region", { name: "Systemstatus" });
    expect(await within(card).findByText("Nicht bereit")).toBeInTheDocument();
    expect(within(card).getByText(/meldet sich nicht bereit/)).toBeInTheDocument();
  });

  it("lists every instance with its status, and a switched-off one as deactivated", async () => {
    answers({
      "GET /api/v1/providers": () => jsonResponse([DEMO_INSTANCE, { ...DEMO_INSTANCE, id: "33333333-3333-4333-8333-333333333333", name: "Off one", enabled: false, status: { ...DEMO_INSTANCE.status, state: "stopped" } }, { ...DEMO_INSTANCE, id: "44444444-4444-4444-8444-444444444444", name: "Broken", status: { ...DEMO_INSTANCE.status, state: "error" } }]),
    });
    renderApp("/");
    const card = await screen.findByRole("region", { name: "Instanzen" });
    const rows = await within(card).findAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText("Workshop demo")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Verbunden")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Deaktiviert")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Fehler")).toBeInTheDocument();
  });

  it("asks for exactly the last ten events and names their source", async () => {
    const calls = answers({ "GET /api/v1/events?limit=10": () => jsonResponse(events(10)) });
    renderApp("/");
    const card = await screen.findByRole("region", { name: "Letzte Ereignisse" });
    expect(await within(card).findAllByRole("listitem")).toHaveLength(10);
    expect(within(card).getAllByText(/Workshop demo/)).toHaveLength(10);
    expect(calls.some((call) => call.path === "/api/v1/events?limit=10")).toBe(true);
  });

  it("says so when there is nothing yet", async () => {
    answers({ "GET /api/v1/providers": () => jsonResponse([]), "GET /api/v1/events?limit=10": () => jsonResponse(events(0)) });
    renderApp("/");
    expect(await screen.findByText("Es gibt noch keine Instanz.")).toBeInTheDocument();
    expect(await screen.findByText("Noch keine Ereignisse.")).toBeInTheDocument();
  });

  it("a failed read of one card does not take the others down and can be retried", async () => {
    let fails = true;
    answers({ "GET /api/v1/events?limit=10": () => (fails ? problemResponse(500, "boom", "x") : jsonResponse(events(1))) });
    renderApp("/");
    const card = await screen.findByRole("region", { name: "Letzte Ereignisse" });
    expect(await within(card).findByRole("alert")).toHaveTextContent("Etwas ist schiefgegangen.");
    expect(await screen.findByText("Workshop demo")).toBeInTheDocument();
    fails = false;
    within(card).getByRole("button", { name: "Erneut versuchen" }).click();
    expect(await within(card).findAllByRole("listitem")).toHaveLength(1);
  });

  it("an event of a deleted instance reads as such, not as the bridge", async () => {
    answers({ "GET /api/v1/events?limit=10": () => jsonResponse({ items: [{ ...EVENT, source_instance_id: "99999999-9999-4999-8999-999999999999" }], next_cursor: null }) });
    renderApp("/");
    expect(await screen.findByText(/Gelöschte Instanz/)).toBeInTheDocument();
  });
});

describe("error type", () => {
  it("ApiError carries the status the pages read", () => {
    expect(new ApiError(503, null, "x").status).toBe(503);
  });
});
