import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VERSION_HEADER } from "../../api/client";
import { INFO, jsonResponse, problemResponse, renderWithProviders, stubFetch } from "../../test-utils";
import { DevicePage, type DeviceEnvironment } from "./DevicePage";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function environment(overrides: Partial<DeviceEnvironment> = {}): DeviceEnvironment {
  return {
    protocol: "https:",
    displayMode: "browser",
    platform: "other",
    serviceWorker: () => Promise.resolve({ supported: true, registered: true, active: true, waiting: false, controlled: true }),
    ...overrides,
  };
}

/** The value next to a label in the facts list. */
function fact(label: string): HTMLElement {
  const term = screen.getByText(label, { selector: "dt" });
  return term.nextElementSibling as HTMLElement;
}

function serve(sessionAnswer: () => Response, info: Record<string, unknown> = INFO) {
  return stubFetch({
    "GET /api/v1/info": () => jsonResponse(info, { headers: { [VERSION_HEADER]: `${String(info.version)}+${String(info.build)}` } }),
    "GET /api/v1/auth/session": sessionAnswer,
  });
}

describe("DevicePage", () => {
  it("names connection, display mode, worker, both builds and the API with its sign-in path", async () => {
    serve(() => jsonResponse({ kind: "session", scope: "admin", user: "admin", csrf_token: "c" }));
    renderWithProviders(<DevicePage environment={environment({ displayMode: "standalone" })} />);
    expect(screen.getByRole("heading", { name: "Dieses Gerät" })).toBeInTheDocument();
    expect(fact("HTTPS")).toHaveTextContent("Ja");
    expect(fact("Darstellung")).toHaveTextContent("Installierte App");
    expect(await screen.findByText("Aktiv, diese Seite kommt aus dem Worker")).toBeInTheDocument();
    expect(fact("Build dieser App")).toHaveTextContent(__APP_VERSION__);
    expect(await screen.findByText("0.2.0+abc1234")).toBeInTheDocument();
    expect(await screen.findByText("Erreichbar, angemeldet")).toBeInTheDocument();
    expect(fact("API")).toHaveTextContent("GET /api/v1/auth/session");
  });

  it("plain http is named, and the worker says it needs a secure connection", async () => {
    serve(() => jsonResponse({ kind: "session", scope: "admin", user: "admin", csrf_token: "c" }));
    renderWithProviders(
      <DevicePage environment={environment({ protocol: "http:", serviceWorker: () => Promise.resolve({ supported: false, registered: false, active: false, waiting: false, controlled: false }) })} />,
    );
    expect(fact("HTTPS")).toHaveTextContent("Nein");
    expect(await screen.findByText("Nicht verfügbar (braucht HTTPS)")).toBeInTheDocument();
  });

  it("a waiting worker and a server on another build are shown as such", async () => {
    serve(() => jsonResponse({ kind: "session", scope: "admin", user: "admin", csrf_token: "c" }), { ...INFO, version: "0.3.0", build: "next" });
    renderWithProviders(
      <DevicePage environment={environment({ serviceWorker: () => Promise.resolve({ supported: true, registered: true, active: true, waiting: true, controlled: true }) })} />,
    );
    expect(await screen.findByText("Aktiv, eine neue Version wartet")).toBeInTheDocument();
    expect(await screen.findByText("Der Server läuft auf einem anderen Build als diese App.")).toBeInTheDocument();
  });

  it("a registered but not yet controlling worker, and none at all", async () => {
    serve(() => jsonResponse({ kind: "session", scope: "admin", user: "admin", csrf_token: "c" }));
    const { unmount } = renderWithProviders(
      <DevicePage environment={environment({ serviceWorker: () => Promise.resolve({ supported: true, registered: true, active: true, waiting: false, controlled: false }) })} />,
    );
    expect(await screen.findByText("Aktiv ab dem nächsten Laden")).toBeInTheDocument();
    unmount();
    renderWithProviders(
      <DevicePage environment={environment({ serviceWorker: () => Promise.resolve({ supported: true, registered: false, active: false, waiting: false, controlled: false }) })} />,
    );
    expect(await screen.findByText("Nicht registriert")).toBeInTheDocument();
  });

  it("the sign-in path answering 401, a login page or nothing at all", async () => {
    serve(() => problemResponse(401, "not_authenticated", "Authentication required"));
    const { unmount } = renderWithProviders(<DevicePage environment={environment()} />);
    expect(await screen.findByText("Erreichbar, nicht angemeldet (401)")).toBeInTheDocument();
    unmount();

    serve(() => new Response("<html>login</html>", { status: 200, headers: { "Content-Type": "text/html" } }));
    const second = renderWithProviders(<DevicePage environment={environment()} />);
    expect(await screen.findByText("Ein Proxy antwortet mit einer Anmeldeseite")).toBeInTheDocument();
    second.unmount();

    stubFetch({ "GET /api/v1/info": () => Promise.reject(new TypeError("offline")), "GET /api/v1/auth/session": () => Promise.reject(new TypeError("offline")) });
    renderWithProviders(<DevicePage environment={environment()} />);
    expect(await screen.findByText("Nicht erreichbar")).toBeInTheDocument();
    expect(await screen.findByText("Unbekannt (Server nicht erreichbar)")).toBeInTheDocument();
  });

  it("checks again on request", async () => {
    let answer = () => problemResponse(503, "database_unavailable", "Database unavailable");
    const calls = serve(() => answer());
    const user = userEvent.setup();
    renderWithProviders(<DevicePage environment={environment()} />);
    expect(await screen.findByText("Fehler 503")).toBeInTheDocument();
    answer = () => jsonResponse({ kind: "session", scope: "admin", user: "admin", csrf_token: "c" });
    await user.click(screen.getByRole("button", { name: "Erneut prüfen" }));
    expect(await screen.findByText("Erreichbar, angemeldet")).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/api/v1/auth/session")).toHaveLength(2);
  });

  it("offers install steps for iOS in a sheet when not installed; not once installed", async () => {
    serve(() => jsonResponse({ kind: "session", scope: "admin", user: "admin", csrf_token: "c" }));
    const user = userEvent.setup();
    const { unmount } = renderWithProviders(<DevicePage environment={environment({ platform: "ios" })} />);
    await user.click(screen.getByRole("button", { name: "Als App installieren" }));
    const sheet = await screen.findByRole("dialog", { name: "Als App installieren" });
    expect(within(sheet).getByText(/Teilen/)).toBeInTheDocument();
    expect(within(sheet).getByText(/Zum Home-Bildschirm/)).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Fertig" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    unmount();

    renderWithProviders(<DevicePage environment={environment({ platform: "ios", displayMode: "standalone" })} />);
    expect(screen.queryByRole("button", { name: "Als App installieren" })).toBeNull();
  });

  it("the default environment reads the browser", async () => {
    serve(() => jsonResponse({ kind: "session", scope: "admin", user: "admin", csrf_token: "c" }));
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query === "(display-mode: minimal-ui)", media: query, addEventListener() {}, removeEventListener() {} }));
    renderWithProviders(<DevicePage />);
    expect(fact("HTTPS")).toHaveTextContent("Nein");
    expect(fact("Darstellung")).toHaveTextContent("Browser (minimale Leiste)");
    // jsdom has no service worker API.
    expect(await screen.findByText("Nicht verfügbar (braucht HTTPS)")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
