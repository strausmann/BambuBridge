import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { DEMO_INSTANCE, DEMO_TYPE, EVENT, jsonResponse, problemResponse, renderApp, SIGNED_IN, stubFetch } from "../../test-utils";
import { communicationQuery } from "./CommunicationPage";
import { eventsQuery } from "./EventsPage";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

type Handler = (init: RequestInit) => Response | Promise<Response>;
const NO_FILTER = { range: { from: "", to: "" }, source: "", type: "", status: "" };
const NO_COMM_FILTER = { range: { from: "", to: "" }, instance: "", status: "" };

const ENTRY = {
  id: "55555555-5555-4555-8555-555555555555",
  occurred_at: "2026-11-17T09:00:00Z",
  instance_id: DEMO_INSTANCE.id,
  direction: "outbound",
  method: "GET",
  target: "demo://tick?token=***",
  status: 200,
  duration_ms: 12,
  truncated: false,
  error: null,
} as const;

function answers(extra: Record<string, Handler> = {}) {
  return stubFetch({
    ...SIGNED_IN,
    "GET /api/v1/providers": () => jsonResponse([DEMO_INSTANCE]),
    "GET /api/v1/provider-types": () => jsonResponse([DEMO_TYPE]),
    [`GET ${eventsQuery(NO_FILTER, null)}`]: () => jsonResponse({ items: [EVENT], next_cursor: null }),
    ...extra,
  });
}

describe("query strings", () => {
  it("events: only the filters that are set, the range as ISO times with a zone", () => {
    expect(eventsQuery(NO_FILTER, null)).toBe("/api/v1/events?limit=50");
    const query = new URL(eventsQuery({ range: { from: "2026-11-17T08:00", to: "2026-11-17T10:00" }, source: "s-1", type: "a.b", status: "failed" }, "cur"), "http://x").searchParams;
    expect(query.get("from")).toMatch(/^2026-11-17T\d\d:00:00\.000Z$/);
    expect(query.get("to")).toMatch(/Z$/);
    expect([query.get("source"), query.get("type"), query.get("status"), query.get("cursor")]).toEqual(["s-1", "a.b", "failed", "cur"]);
  });

  it("communication: instance and status class", () => {
    expect(communicationQuery(NO_COMM_FILTER, null)).toBe("/api/v1/communication?limit=50");
    const query = new URL(communicationQuery({ range: { from: "", to: "" }, instance: "i-1", status: "4xx" }, null), "http://x").searchParams;
    expect([query.get("instance"), query.get("status")]).toEqual(["i-1", "4xx"]);
  });

  it("a half-typed time is left out instead of sent", () => {
    expect(eventsQuery({ ...NO_FILTER, range: { from: "not a time", to: "" } }, null)).toBe("/api/v1/events?limit=50");
  });
});

describe("events", () => {
  it("lists the events newest first and opens the detail with payload and deliveries", async () => {
    const user = userEvent.setup();
    answers({
      [`GET /api/v1/events/${EVENT.id}`]: () =>
        jsonResponse({ ...EVENT, deliveries: [{ subscriber: "sse", status: "done", attempts: 1, last_error: null }, { subscriber: "hook", status: "failed", attempts: 3, last_error: "connection refused" }] }),
    });
    renderApp("/protocol");
    const list = await screen.findByRole("list", { name: "Ereignisse" });
    expect(within(list).getByText("integration.demo.tick")).toBeInTheDocument();
    expect(within(list).getByText(/Workshop demo/)).toBeInTheDocument();

    await user.click(within(list).getByRole("button", { name: /integration\.demo\.tick/ }));
    const detail = await screen.findByTestId("event-detail");
    expect(within(detail).getByLabelText("Nutzdaten des Ereignisses")).toHaveTextContent('"sequence": 7');
    expect(within(detail).getByText("connection refused")).toBeInTheDocument();
    expect(within(detail).getByText("Versuche: 3")).toBeInTheDocument();
  });

  it("filtering by type, source and delivery asks the server and shows what it returns", async () => {
    const user = userEvent.setup();
    const calls = answers({
      [`GET ${eventsQuery({ ...NO_FILTER, type: "integration.demo.tick" }, null)}`]: () => jsonResponse({ items: [], next_cursor: null }),
    });
    renderApp("/protocol");
    await screen.findByRole("list", { name: "Ereignisse" });
    await user.selectOptions(screen.getByLabelText("Ereignistyp"), "integration.demo.tick");
    expect(await screen.findByText("Keine Ereignisse für diese Filter.")).toBeInTheDocument();
    expect(calls.some((call) => call.path.includes("type=integration.demo.tick"))).toBe(true);
  });

  it("a time range goes out as ISO times", async () => {
    const user = userEvent.setup();
    const calls = answers();
    renderApp("/protocol");
    await screen.findByRole("list", { name: "Ereignisse" });
    const from = screen.getByLabelText("Von");
    await user.type(from, "2026-11-17T08:00");
    await waitFor(() => expect(calls.some((call) => /from=2026-11-17T\d\d%3A00%3A00\.000Z/.test(call.path))).toBe(true));
  });

  it("loads older events with the cursor of the page", async () => {
    const user = userEvent.setup();
    const second = { ...EVENT, id: "66666666-6666-4666-8666-666666666666", type: "integration.demo.older" };
    const calls = answers({
      [`GET ${eventsQuery(NO_FILTER, null)}`]: () => jsonResponse({ items: [EVENT], next_cursor: "CUR1" }),
      [`GET ${eventsQuery(NO_FILTER, "CUR1")}`]: () => jsonResponse({ items: [second], next_cursor: null }),
    });
    renderApp("/protocol");
    await user.click(await screen.findByRole("button", { name: "Ältere laden" }));
    expect(await screen.findByText("integration.demo.older")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ältere laden" })).not.toBeInTheDocument();
    expect(calls.some((call) => call.path.includes("cursor=CUR1"))).toBe(true);
  });

  it("says so when there are no events, and when the read fails", async () => {
    answers({ [`GET ${eventsQuery(NO_FILTER, null)}`]: () => jsonResponse({ items: [], next_cursor: null }) });
    const first = renderApp("/protocol");
    expect(await screen.findByText("Noch keine Ereignisse.")).toBeInTheDocument();
    first.unmount();
    answers({ [`GET ${eventsQuery(NO_FILTER, null)}`]: () => problemResponse(500, "boom", "x") });
    renderApp("/protocol");
    expect(await screen.findByRole("alert")).toHaveTextContent("Etwas ist schiefgegangen.");
  });

  it("a very long event type and many events stay inside the list", async () => {
    const many = Array.from({ length: 200 }, (_, i) => ({ ...EVENT, id: `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`, type: `${"very.long.".repeat(30)}${i}` }));
    answers({ [`GET ${eventsQuery(NO_FILTER, null)}`]: () => jsonResponse({ items: many, next_cursor: null }) });
    renderApp("/protocol");
    const list = await screen.findByRole("list", { name: "Ereignisse" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(200);
    expect(within(list).getAllByText(/very\.long\./)[0]!.tagName).toBe("CODE");
    expect(within(list).getAllByText(/very\.long\./)[0]!.className).toContain("break-all");
  });
});

describe("communication", () => {
  const open = async () => {
    const user = userEvent.setup();
    renderApp("/protocol");
    await user.click(await screen.findByRole("tab", { name: "Kommunikation" }));
    return user;
  };

  it("lists the calls with their answer and shows a masked token as it was stored", async () => {
    answers({
      [`GET ${communicationQuery({ range: { from: "", to: "" }, instance: "", status: "" }, null)}`]: () => jsonResponse({ items: [ENTRY, { ...ENTRY, id: "77777777-7777-4777-8777-777777777777", status: null, error: "timeout" }], next_cursor: null }),
      [`GET /api/v1/communication/${ENTRY.id}`]: () =>
        jsonResponse({ ...ENTRY, request_headers: { Authorization: "***" }, request_body: null, response_headers: {}, response_body: '{"echo":"***"}' }),
    });
    const user = await open();
    const list = await screen.findByRole("list", { name: "Kommunikation" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).getByText("200")).toBeInTheDocument();
    expect(within(list).getByText("Keine Antwort")).toBeInTheDocument();
    // The list itself shows the masked target, never a token.
    expect(within(list).getAllByText("demo://tick?token=***")).toHaveLength(2);

    await user.click(within(list).getAllByRole("button")[0]!);
    const detail = await screen.findByTestId("communication-detail");
    expect(within(detail).getByText("demo://tick?token=***")).toBeInTheDocument();
    expect(within(detail).getByLabelText("Anfrage: Kopfzeilen")).toHaveTextContent('"Authorization": "***"');
    expect(within(detail).getByLabelText("Antwort: Inhalt")).toHaveTextContent("***");
  });

  it("filters by the class of the answer", async () => {
    const user = userEvent.setup();
    const calls = answers({
      [`GET ${communicationQuery({ range: { from: "", to: "" }, instance: "", status: "5xx" }, null)}`]: () => jsonResponse({ items: [], next_cursor: null }),
    });
    renderApp("/protocol");
    await user.click(await screen.findByRole("tab", { name: "Kommunikation" }));
    await user.selectOptions(await screen.findByLabelText("Antwort"), "5xx");
    expect(await screen.findByText("Keine Einträge für diese Filter.")).toBeInTheDocument();
    expect(calls.some((call) => call.path.includes("status=5xx"))).toBe(true);
  });
});
