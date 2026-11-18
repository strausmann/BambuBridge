import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { setCsrfToken } from "../api/client";
import { INFO, jsonResponse, problemResponse, renderApp, SESSION, stubFetch } from "../test-utils";

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
  setCsrfToken(null);
});

function signedIn(info: () => Response = () => jsonResponse(INFO)) {
  return stubFetch({ "GET /api/v1/auth/session": () => jsonResponse(SESSION), "GET /api/v1/info": info });
}

describe("app shell", () => {
  it("offers the same four destinations in the sidebar and in the tab bar", async () => {
    signedIn();
    renderApp("/");
    await screen.findByRole("heading", { name: "Übersicht" });
    const navigations = screen.getAllByRole("navigation", { name: "Hauptnavigation" });
    expect(navigations).toHaveLength(2);
    for (const navigation of navigations) {
      const links = within(navigation).getAllByRole("link");
      expect(links.map((link) => link.textContent)).toEqual(["Übersicht", "Anbieter", "Protokoll", "Einstellungen"]);
      expect(links.map((link) => link.getAttribute("href"))).toEqual(["/", "/providers", "/protocol", "/settings"]);
    }
  });

  it("the device page, reached from the settings, keeps 'Einstellungen' marked in the sidebar and the tab bar", async () => {
    signedIn();
    renderApp("/device");
    await screen.findByRole("heading", { name: "Dieses Gerät" });
    const navigations = screen.getAllByRole("navigation", { name: "Hauptnavigation" });
    expect(navigations).toHaveLength(2);
    for (const navigation of navigations) {
      const settings = within(navigation).getByRole("link", { name: "Einstellungen" });
      expect(settings).toHaveAttribute("aria-current", "page");
      expect(settings).toHaveAttribute("data-status", "active");
      expect(within(navigation).getByRole("link", { name: "Übersicht" })).not.toHaveAttribute("aria-current");
    }
  });

  it("marks the current page for assistive technology and moves with navigation", async () => {
    signedIn();
    const user = userEvent.setup();
    const { router } = renderApp("/");
    await screen.findByRole("heading", { name: "Übersicht" });
    const sidebar = screen.getAllByRole("navigation", { name: "Hauptnavigation" })[0]!;
    expect(within(sidebar).getByRole("link", { name: "Übersicht" })).toHaveAttribute("aria-current", "page");

    await user.click(within(sidebar).getByRole("link", { name: "Einstellungen" }));
    expect(await screen.findByRole("heading", { name: "Einstellungen" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/settings");
    expect(within(sidebar).getByRole("link", { name: "Einstellungen" })).toHaveAttribute("aria-current", "page");
    // The overview matches only its exact path.
    expect(within(sidebar).getByRole("link", { name: "Übersicht" })).not.toHaveAttribute("aria-current");
  });

  it("has every route of the foundation", async () => {
    signedIn();
    for (const [path, heading] of [
      ["/providers", "Anbieter"],
      ["/protocol", "Protokoll"],
      ["/settings/access", "Zugang"],
      ["/settings/unknown-section", "Einstellung nicht gefunden"],
      ["/device", "Dieses Gerät"],
    ] as const) {
      const { unmount } = renderApp(path);
      expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
      unmount();
    }
  });

  it("the skip link moves focus to the content", async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp("/");
    await screen.findByRole("heading", { name: "Übersicht" });
    await user.click(screen.getByRole("link", { name: "Zum Inhalt springen" }));
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("shows the server version, and says so when the server does not answer", async () => {
    signedIn();
    const first = renderApp("/");
    expect(await screen.findByText("Version 0.2.0")).toBeInTheDocument();
    first.unmount();

    signedIn(() => problemResponse(404, "not_found", "Not found"));
    renderApp("/");
    expect(await screen.findByText("Server nicht erreichbar")).toBeInTheDocument();
  });

  it("uses the brand logo files, one drawing per theme, and names it once", async () => {
    signedIn();
    renderApp("/");
    await screen.findByRole("heading", { name: "Übersicht" });
    const lockup = document.querySelector('[data-logo="lockup"]')!;
    const images = lockup.querySelectorAll("img");
    expect(images).toHaveLength(2);
    expect(images[0]).toHaveAttribute("alt", "BambuBridge");
    expect(images[0]!.getAttribute("src")).toContain("drehscheibe-light-lockup");
    expect(images[1]).toHaveAttribute("aria-hidden", "true");
    expect(images[1]!.getAttribute("src")).toContain("drehscheibe-dark-lockup");
  });
});
