import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test-utils";
import { ConnectionBanner } from "./ConnectionBanner";
import { NOTICE_GAP_PX, NoticeArea } from "./Notice";

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

describe("NoticeArea", () => {
  it("publishes the height of its notes as --notice-h, so the page can keep its last controls clear", () => {
    let report: ((entries: { contentRect: { height: number } }[]) => void) | undefined;
    const disconnect = vi.fn();
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: typeof report) {
          report = callback;
        }
        observe() {}
        disconnect = disconnect;
      },
    );
    const root = document.documentElement;
    const { unmount } = renderWithProviders(<NoticeArea aboveTabBar>{null}</NoticeArea>);
    act(() => report!([{ contentRect: { height: 56 } }]));
    expect(root.style.getPropertyValue("--notice-h")).toBe(`${56 + NOTICE_GAP_PX}px`);
    // Nothing shown: nothing to keep clear.
    act(() => report!([{ contentRect: { height: 0 } }]));
    expect(root.style.getPropertyValue("--notice-h")).toBe("0px");
    unmount();
    expect(disconnect).toHaveBeenCalled();
    expect(root.style.getPropertyValue("--notice-h")).toBe("");
    vi.unstubAllGlobals();
  });
});
