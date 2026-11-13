import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test-utils";
import { ConnectionBanner } from "./ConnectionBanner";

afterEach(() => vi.restoreAllMocks());

describe("ConnectionBanner", () => {
  it("appears when the browser goes offline and leaves when it is back", () => {
    let online = true;
    vi.spyOn(navigator, "onLine", "get").mockImplementation(() => online);
    renderWithProviders(<ConnectionBanner />);
    expect(screen.queryByRole("status")).toBeNull();
    act(() => {
      online = false;
      window.dispatchEvent(new Event("offline"));
    });
    expect(screen.getByRole("status")).toHaveTextContent("Keine Verbindung");
    expect(screen.getByRole("status")).toHaveTextContent("Daten werden erst wieder angezeigt");
    act(() => {
      online = true;
      window.dispatchEvent(new Event("online"));
    });
    expect(screen.queryByRole("status")).toBeNull();
  });
});
