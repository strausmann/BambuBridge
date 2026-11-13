import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { INFO, jsonResponse, renderApp, SESSION, stubFetch } from "../test-utils";
import { createAppRouter } from "./router";
import { PARAMETER_ROUTES, PUBLIC_PAGES, SHELL_PAGES } from "./routes";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

describe("route list", () => {
  it("names exactly the routes the router has", () => {
    const router = createAppRouter();
    // Layout and index route share a path ("/settings" and "/settings/"), as do the root and "/".
    const paths = new Set(Object.values(router.routesById).map((route) => String(route.fullPath).replace(/(.)\/$/, "$1")));
    expect([...paths].sort()).toEqual([...SHELL_PAGES, ...PUBLIC_PAGES, ...PARAMETER_ROUTES].sort());
  });

  it("the settings page lists the pages below the main destinations", async () => {
    stubFetch({ "GET /api/v1/auth/session": () => jsonResponse(SESSION), "GET /api/v1/info": () => jsonResponse(INFO) });
    const user = userEvent.setup();
    const { router } = renderApp("/settings");
    const list = await screen.findByRole("navigation", { name: "Einstellungsseiten" });
    await user.click(within(list).getByRole("link", { name: /Dieses Gerät/ }));
    expect(router.state.location.pathname).toBe("/device");
  });
});
