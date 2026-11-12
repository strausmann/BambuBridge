import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SHORT_VIEWPORT_PX, useShortViewport } from "./useShortViewport";

function Probe() {
  return <p data-testid="probe" data-short={useShortViewport() || undefined} />;
}

class FakeViewport extends EventTarget {
  height = 800;
  scale = 1;
}

afterEach(() => vi.unstubAllGlobals());

describe("useShortViewport", () => {
  it("follows the visible height: short while the on-screen keyboard covers the page", () => {
    const viewport = new FakeViewport();
    vi.stubGlobal("visualViewport", viewport);
    render(<Probe />);
    expect(screen.getByTestId("probe")).not.toHaveAttribute("data-short");

    act(() => {
      viewport.height = SHORT_VIEWPORT_PX - 1;
      viewport.dispatchEvent(new Event("resize"));
    });
    expect(screen.getByTestId("probe")).toHaveAttribute("data-short");

    act(() => {
      viewport.height = SHORT_VIEWPORT_PX + 1;
      viewport.dispatchEvent(new Event("resize"));
    });
    expect(screen.getByTestId("probe")).not.toHaveAttribute("data-short");
  });

  it("starts short when the page opens with little room", () => {
    const viewport = new FakeViewport();
    viewport.height = 300;
    vi.stubGlobal("visualViewport", viewport);
    render(<Probe />);
    expect(screen.getByTestId("probe")).toHaveAttribute("data-short");
  });

  it("stops listening when the screen is gone", () => {
    const viewport = new FakeViewport();
    const remove = vi.spyOn(viewport, "removeEventListener");
    vi.stubGlobal("visualViewport", viewport);
    render(<Probe />).unmount();
    expect(remove).toHaveBeenCalledWith("resize", expect.any(Function));
  });

  it("is never short where the browser has no visual viewport (the media query still applies)", () => {
    vi.stubGlobal("visualViewport", undefined);
    render(<Probe />);
    expect(screen.getByTestId("probe")).not.toHaveAttribute("data-short");
  });

  it("ignores pinch-zoom: a zoomed page shows less, but no keyboard is open", () => {
    const viewport = new FakeViewport();
    vi.stubGlobal("visualViewport", viewport);
    render(<Probe />);
    act(() => {
      viewport.height = 300;
      viewport.scale = 2;
      viewport.dispatchEvent(new Event("resize"));
    });
    expect(screen.getByTestId("probe")).not.toHaveAttribute("data-short");
    act(() => {
      viewport.scale = 1.005; // rounding of an unzoomed page
      viewport.dispatchEvent(new Event("resize"));
    });
    expect(screen.getByTestId("probe")).toHaveAttribute("data-short");
  });
});
